"""網頁後台

分兩層，方便"本地後台"與"遠端中繼站"共用同一套邏輯：
- DashboardCore：與傳輸方式無關，工作階段（一個瀏覽器分頁一個）、身分判斷、權限、操作分派、廣播
- Dashboard：本地的 aiohttp 伺服器（靜態頁面 + WebSocket），把瀏覽器連線接到 DashboardCore
  遠端中繼站（relay.py / relay_client.py）也是把瀏覽器連線接到同一個 DashboardCore

存取控制（見 Hub 與 README"誰能做什麼"）：
- 從執行機器人的這台電腦直接開 http://localhost:埠 = 本地主人，不需要憑證
- 開放模式（預設）：其他人知道網址就能控制所有頻道（訪客）；/help 的擁有者連結才有擁有者權限
- 驗證模式：點 /help 給的專屬連結進來（自動綁定 Discord 身分並記住這個瀏覽器），沒有連結什麼都不能做
- 語音模式：必須帶 /help 簽出的憑證，而且人要在語音頻道裡才能控制
- 只接受同源的 WebSocket，其他網站無法偷連你的後台

The web dashboard.

Two layers, so the "local dashboard" and the "remote relay" can share the same logic:
- DashboardCore: independent of the transport. Sessions (one per browser tab), identity checks, permissions,
  action dispatch and broadcasting.
- Dashboard: the local aiohttp server (static page + WebSocket) that plugs browser connections into
  DashboardCore. The remote relay (relay.py / relay_client.py) plugs browsers into the same DashboardCore.

Access control (see Hub and the README section "誰能做什麼 / who can do what"):
- Opening http://localhost:<port> on the machine running the bot = local owner, no token needed.
- open mode (default): anyone who knows the URL can control every channel (as a guest); only the owner
  link from /help grants owner rights.
- verify mode: come in through the personal link from /help (binds the Discord identity and remembers the
  browser); without it nothing can be done.
- voice mode: a token signed by /help is required, and you must be in a voice channel to control playback.
- Only same-origin WebSockets are accepted, so other websites can't connect to your dashboard behind your back.

Browser <-> server messages (JSON) / 瀏覽器與伺服器之間的訊息:
  server -> browser:  state | toast | error | verified | revoked | (Bilibili login progress messages)
  browser -> server:  select | bili_login_start | bili_login_cancel | <any action handled by Hub.handle_action>
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import urlparse

from aiohttp import WSMsgType, web

from . import auth
from .hub import Hub, UserCtx
from .webutil import secure_headers

log = logging.getLogger("musicbot.dashboard")

Emit = Callable[[dict], Awaitable[None]]   # "把一則訊息送給某個瀏覽器"的函式型別 / type of "send one message to one browser"

# 經過反向代理／通道（例如 cloudflared、ngrok）進來的請求會帶這些標頭，不能當作本地
# Requests that arrive through a reverse proxy / tunnel (cloudflared, ngrok...) carry these headers, so they must not be treated as local.
_PROXY_HEADERS = ("X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto", "Forwarded",
                  "X-Real-IP", "CF-Connecting-IP", "CF-Ray", "True-Client-IP")
_LOOPBACK = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def clean_name(raw: object) -> str:
    """訪客暱稱：只留可顯示字元、最多 16 字

    Guest nickname: keep printable characters only, at most 16 characters.
    """
    return "".join(ch for ch in str(raw or "") if ch.isprintable()).strip()[:16]


@dataclass(eq=False)
class Session:
    """一個瀏覽器分頁

    One browser tab connected to the dashboard.
    """
    gid: int                                        # 它看的是哪個伺服器 / which guild (server) it is looking at
    ctx: UserCtx                                    # 它是誰、能做什麼 / who it is and what it may do
    emit: Emit                                      # 把訊息送回這個瀏覽器 / sends a message back to this browser
    pid: str | None = None                          # 使用者在介面上選的播放器；None = 自動跟著他所在的頻道 / the player picked in the UI; None = follow the channel the user is in
    bili_task: asyncio.Task | None = None           # 進行中的 Bilibili QR 登入流程 / the running Bilibili QR-login flow, if any


# ============================================================
# 核心：與傳輸方式無關 / Core: transport-independent logic
# ============================================================
class DashboardCore:
    """管理所有工作階段，處理身分、操作與廣播

    Manages all sessions: identity, actions and broadcasting.
    """

    def __init__(self, hub: Hub) -> None:
        self.hub = hub
        self.sessions: dict[int, set[Session]] = {}   # guild id -> 該伺服器所有分頁 / all tabs of that guild
        self._pending: set[int] = set()               # 已排程、等待廣播的伺服器 / guilds with a broadcast already scheduled

    # ------------------------------------------------------------
    # 身分 / Identity
    # ------------------------------------------------------------
    async def authenticate(self, gid: int, token: str | None, name: str | None, is_local: bool,
                           device: str | None = None) -> UserCtx | None:
        """決定這個連線是誰、能做什麼；不被允許就回傳 None
        is_local 只有"真的是這台電腦上的瀏覽器直連 localhost"才會是 True（經過中繼站的永遠是 False）
        token = /help 簽出的連結憑證；device = 驗證後主機記住的裝置憑證

        Decide who this connection is and what it may do; returns None when not allowed.
        ``is_local`` is True only for a browser on this very machine talking to localhost directly (always
        False through the relay). ``token`` = the link token signed by /help; ``device`` = the device token
        the host remembered after verification.

        Order of checks / 檢查順序: link token -> remembered device -> local owner -> guest (open mode)
        -> pending (verify mode) -> refused.
        """
        hub = self.hub
        if token:
            ident = auth.verify_token(hub.secret, token)
            if ident and ident.guild_id == gid:
                return hub.ctx_from_token(ident)
            if hub.mode == "voice":            # 語音模式：憑證不對就進不來 / voice mode: a bad token means no entry
                return None
        if hub.mode == "verify" and device:
            rec = hub.members.lookup(device)
            if rec and rec["gid"] == str(gid):
                uid = int(rec["uid"])
                nick = await hub.member_name(gid, uid, rec["name"])   # 順便抓他現在的暱稱 / also fetch their current nickname
                if nick is not None:
                    return UserCtx(uid, nick, is_owner=uid in hub.owner_ids, via="device")
                hub.members.revoke_user(uid)   # 已經不在伺服器裡了：撤銷 / no longer in the server: revoke
        if is_local:
            return hub.host_ctx()
        if hub.mode == "open":                 # 開放模式：知道網址就能用（訪客，沒有擁有者權限）/ open mode: knowing the URL is enough (guest, no owner rights)
            return hub.guest_ctx(clean_name(name))
        if hub.mode == "verify":               # 驗證模式：先去驗證，什麼都不能做 / verify mode: must verify first, nothing can be done meanwhile
            return hub.pending_ctx()
        return None

    # ------------------------------------------------------------
    # 工作階段 / Sessions
    # ------------------------------------------------------------
    async def open_session(self, gid: int, ctx: UserCtx, emit: Emit) -> Session | None:
        """建立工作階段並送出第一份狀態；機器人不在該伺服器就回傳 None

        Create a session and send the first state snapshot; returns None if the bot isn't in that guild.
        """
        snap = self.hub.snapshot(gid, ctx, None)
        if snap is None:
            await emit({"type": "error", "code": "guild", "text": "機器人不在這個伺服器，請確認網址"})
            return None
        sess = Session(gid, ctx, emit)
        self.sessions.setdefault(gid, set()).add(sess)
        await emit({"type": "state", "data": snap})
        if self.hub.mode == "verify" and ctx.user_id and ctx.via == "link":
            # 用 /help 的連結進來：身分已經確定，直接替這個瀏覽器登記成"記住的裝置"，以後不用再點連結
            # Came in through a /help link: the identity is settled, so register this browser as a
            # "remembered device" right away; no need to click the link again next time.
            await emit({"type": "verified", "token": self.hub.issue_device(ctx, gid), "name": ctx.name})
        return sess

    def demote(self, uid: int) -> None:
        """這個人被撤銷：他所有正在連線的瀏覽器立刻回到未驗證，並要求清掉瀏覽器裡的憑證

        This user was revoked: all of their open browsers drop back to "unverified" immediately and are
        told to erase the token stored in the browser.
        """
        for group in list(self.sessions.values()):
            for sess in list(group):
                if sess.ctx.user_id == uid and sess.ctx.via in ("device", "link") and not sess.ctx.is_host:
                    sess.ctx = self.hub.pending_ctx()
                    asyncio.create_task(self._demote_notify(sess))

    async def _demote_notify(self, sess: Session) -> None:
        """通知瀏覽器"你被撤銷了"並送出降級後的狀態 / Tell the browser it was revoked and send the downgraded state."""
        await self._safe_emit(sess, {"type": "revoked"})
        snap = self.hub.snapshot(sess.gid, sess.ctx, None)
        if snap:
            await self._safe_emit(sess, {"type": "state", "data": snap})

    def close(self, sess: Session) -> None:
        """結束一個工作階段並取消它的背景工作 / End one session and cancel its background work."""
        self._cancel_bili(sess)
        self.sessions.get(sess.gid, set()).discard(sess)

    def close_all(self) -> None:
        """結束所有工作階段 / End every session."""
        for group in list(self.sessions.values()):
            for sess in list(group):
                self.close(sess)

    # ------------------------------------------------------------
    # 處理瀏覽器訊息 / Handling browser messages
    # ------------------------------------------------------------
    async def handle(self, sess: Session, data: dict) -> None:
        """處理瀏覽器送來的一則訊息

        Handle one message sent by a browser.
        """
        t = data.get("type")
        if sess.ctx.pending:        # 還沒用連結確認身分：什麼都不能做 / identity not confirmed through a link yet: nothing is allowed
            await self._safe_emit(sess, {"type": "toast", "text": "請先在 Discord 輸入 /help，點它給你的專屬連結"})
            return
        if t == "select":
            sess.pid = str(data.get("pid") or "") or None
            snap = self.hub.snapshot(sess.gid, sess.ctx, sess.pid)
            if snap:
                await self._safe_emit(sess, {"type": "state", "data": snap})
        elif t == "bili_login_start":
            if not self.hub.is_owner(sess.ctx):
                await self._safe_emit(sess, {"type": "toast", "text": "只有機器人的擁有者可以更換 Bilibili 帳號"})
                return
            self._cancel_bili(sess)
            sess.bili_task = asyncio.create_task(self.hub.bili_login_flow(lambda m: self._safe_emit(sess, m)))
        elif t == "bili_login_cancel":
            self._cancel_bili(sess)
        else:
            # 每個操作各自跑，避免一個慢的解析卡住其他拖曳操作
            # Each action runs on its own so one slow lookup can't block other drag-and-drop actions.
            asyncio.create_task(self._run_action(sess, data))

    @staticmethod
    def _cancel_bili(sess: Session) -> None:
        """取消進行中的 Bilibili 登入流程 / Cancel a running Bilibili login flow."""
        if sess.bili_task and not sess.bili_task.done():
            sess.bili_task.cancel()
        sess.bili_task = None

    @staticmethod
    async def _safe_emit(sess: Session, msg: dict) -> None:
        """送訊息給瀏覽器；失敗（已斷線）就忽略 / Send to the browser; ignore failures (it has disconnected)."""
        try:
            await sess.emit(msg)
        except Exception:  # noqa: BLE001 - 瀏覽器已斷線，忽略 / the browser is gone; ignore
            pass

    async def _run_action(self, sess: Session, data: dict) -> None:
        """執行一個操作（加歌、跳過、排序…），回報結果，並通知所有人更新

        Run one action (add, skip, reorder...), report the outcome and notify everyone to refresh.
        """
        try:
            note = await self.hub.handle_action(sess.gid, sess.ctx, sess.pid, data)
        except Exception as exc:  # noqa: BLE001
            log.exception("操作失敗：%s", data.get("type"))
            note = f"操作失敗：{str(exc)[:120]}"
        if note:
            await self._safe_emit(sess, {"type": "toast", "text": note})
        self.broadcast(sess.gid)

    # ------------------------------------------------------------
    # 廣播 / Broadcasting
    # ------------------------------------------------------------
    # 合併 50ms 內的多次更新；每個連線各自算自己的快照，因為權限與選的播放器不同
    # Updates within 50 ms are merged; each connection gets its own snapshot because permissions and
    # the selected player differ per viewer.
    def broadcast(self, gid: int) -> None:
        """排程一次狀態廣播（50 毫秒內重複呼叫會合併成一次）

        Schedule a state broadcast for a guild (calls within 50 ms collapse into one).
        """
        if gid in self._pending or not self.sessions.get(gid):
            return
        self._pending.add(gid)
        asyncio.get_running_loop().call_later(0.05, self._flush, gid)

    def _flush(self, gid: int) -> None:
        """真正送出狀態給該伺服器的每個分頁 / Actually send the state to every tab of that guild."""
        self._pending.discard(gid)
        shared: dict = {}          # 這一輪廣播共用：與"是誰在看"無關的部分只算一次 / shared by this round: the viewer-independent parts are computed once
        for sess in list(self.sessions.get(gid, ())):
            snap = self.hub.snapshot(gid, sess.ctx, sess.pid, shared)
            if snap is not None:
                asyncio.create_task(self._safe_emit(sess, {"type": "state", "data": snap}))


# ============================================================
# 本地伺服器 / The local HTTP server
# ============================================================
class Dashboard:
    """本地的 aiohttp 伺服器：把瀏覽器連線接到 DashboardCore

    The local aiohttp server: connects browser sockets to DashboardCore.
    """

    def __init__(self, hub: Hub, web_dir: Path, host: str, port: int) -> None:
        self.hub = hub
        self.core = hub.core
        self.web_dir = Path(web_dir)
        self.host, self.port = host, port
        self._sockets: set[web.WebSocketResponse] = set()
        self._runner: web.AppRunner | None = None

    # ---- 啟動／關閉 / start and stop ----
    async def start(self) -> None:
        """註冊路由並開始監聽 / Register routes and start listening."""
        app = web.Application(middlewares=[secure_headers])
        app.router.add_get("/", self.index)
        app.router.add_get("/g/{gid:\\d+}", self.index)
        app.router.add_get("/api/guilds", self.guilds)
        app.router.add_get("/ws/{gid:\\d+}", self.ws)
        app.router.add_static("/static/", self.web_dir, follow_symlinks=False)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        await web.TCPSite(self._runner, self.host, self.port).start()

    async def stop(self) -> None:
        """關閉所有連線與伺服器 / Close all connections and the server."""
        for ws in list(self._sockets):
            await ws.close()
        if self._runner:
            await self._runner.cleanup()

    # ---- 安全 / security ----
    @staticmethod
    def _same_origin(request: web.Request) -> bool:
        """Origin 必須與網址同源，擋掉別的網站偷開連線 / The Origin must match the page host, blocking cross-site connections."""
        origin = request.headers.get("Origin")
        return origin is None or urlparse(origin).netloc == request.host

    @staticmethod
    def _is_local(request: web.Request) -> bool:
        """真的是這台電腦上的瀏覽器直接連 localhost（不是經過代理／通道轉進來的）

        True only for a browser on this machine connecting straight to localhost (not forwarded by a proxy/tunnel).
        Three checks: the TCP peer is loopback, the Host header is a local name, and no proxy header is present.
        """
        peer = request.transport.get_extra_info("peername") if request.transport else None
        if not peer or peer[0] not in _LOOPBACK:
            return False
        host = urlparse("//" + request.host).hostname or ""
        if host.lower() not in _LOCAL_HOSTS:
            return False
        return not any(h in request.headers for h in _PROXY_HEADERS)

    # ---- 路由 / routes ----
    async def index(self, request: web.Request) -> web.StreamResponse:
        """回傳看板網頁 / Serve the dashboard page."""
        return web.FileResponse(self.web_dir / "index.html")

    async def guilds(self, request: web.Request) -> web.Response:
        """伺服器清單：開放模式或本地才給 / The server list: only in open mode or from the local machine."""
        if not (self.hub.open_access or self._is_local(request)):
            raise web.HTTPForbidden(text="只有本機可以列出伺服器")
        return web.json_response(self.hub.guild_list())

    async def ws(self, request: web.Request) -> web.StreamResponse:
        """瀏覽器的 WebSocket：驗證身分 → 開工作階段 → 收訊息交給 DashboardCore

        A browser's WebSocket: authenticate -> open a session -> pass incoming messages to DashboardCore.
        """
        if not self._same_origin(request):
            raise web.HTTPForbidden(text="cross-origin websocket refused")
        gid = int(request.match_info["gid"])
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)

        async def emit(msg: dict) -> None:
            if not ws.closed:
                await ws.send_str(json.dumps(msg))

        ctx = await self.core.authenticate(
            gid, request.query.get("t"), request.query.get("n"), self._is_local(request), request.query.get("d"))
        if ctx is None:
            await emit({"type": "error", "code": "auth", "text": "連結無效或已過期。請在 Discord 輸入 /help 取得新的連結。"})
            await ws.close()
            return ws
        sess = await self.core.open_session(gid, ctx, emit)
        if sess is None:
            await ws.close()
            return ws

        self._sockets.add(ws)
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                except ValueError:
                    continue
                if isinstance(data, dict):
                    await self.core.handle(sess, data)
        finally:
            self._sockets.discard(ws)
            self.core.close(sess)
        return ws

    # 相容：Hub.notify 以前呼叫 dashboard.broadcast
    # Compatibility: Hub.notify used to call dashboard.broadcast directly.
    def broadcast(self, gid: int) -> None:
        """轉給 DashboardCore.broadcast / Forwards to DashboardCore.broadcast."""
        self.core.broadcast(gid)
