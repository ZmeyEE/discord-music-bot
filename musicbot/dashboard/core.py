"""看板核心：驗證、連線管理、收操作、廣播狀態（本機看板和中繼站共用）

Dashboard core: authentication, sessions, receiving actions, broadcasting state (shared by the local dashboard and the relay)
"""
from __future__ import annotations

import asyncio
import logging

from .. import auth, params
from ..hub import Hub, UserCtx
from .session import Emit, Session, clean_name

log = logging.getLogger("musicbot")

class DashboardCore:
    """管理所有工作階段，處理身分、操作與廣播

    Manages all sessions: identity, actions and broadcasting.
    """

    def __init__(self, hub: Hub) -> None:
        self.hub = hub
        self.sessions: dict[int, set[Session]] = {}   # guild id -> 該伺服器所有分頁 / all tabs of that guild
        self._pending: set[int] = set()               # 已排程、等待廣播的伺服器 / guilds with a broadcast already scheduled

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

    async def open_session(self, gid: int, ctx: UserCtx, emit: Emit) -> Session | None:
        """建立工作階段並送出第一份狀態；機器人不在該伺服器就回傳 None

        Create a session and send the first state snapshot; returns None if the bot isn't in that guild.
        """
        sess = Session(gid, ctx, emit)
        snap = self._state_for(sess)
        if snap is None:
            await emit({"type": "error", "code": "guild", "text": "機器人不在這個伺服器，請確認網址"})
            return None
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
        await self._send_state(sess)

    def close(self, sess: Session) -> None:
        """結束一個工作階段並取消它的背景工作 / End one session and cancel its background work."""
        self._cancel_bili(sess)
        self.sessions.get(sess.gid, set()).discard(sess)

    def close_all(self) -> None:
        """結束所有工作階段 / End every session."""
        for group in list(self.sessions.values()):
            for sess in list(group):
                self.close(sess)

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
            await self._send_state(sess)
        elif t == "queue_window":      # 網頁要更多待播卡片（往下捲），或一連上就告訴我們它懂"沒變就不送" / the page wants more queued cards (scrolling), or says on connect that it understands "unchanged, not sent"
            sess.view.ask(data.get("limit"))
            await self._send_state(sess)
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
        asyncio.get_running_loop().call_later(params.BROADCAST_MERGE_SECONDS, self._flush, gid)

    def _flush(self, gid: int) -> None:
        """真正送出狀態給該伺服器的每個分頁 / Actually send the state to every tab of that guild."""
        self._pending.discard(gid)
        shared: dict = {}          # 這一輪廣播共用：與"是誰在看"無關的部分只算一次 / shared by this round: the viewer-independent parts are computed once
        for sess in list(self.sessions.get(gid, ())):
            snap = self._state_for(sess, shared)
            if snap is not None:
                asyncio.create_task(self._safe_emit(sess, {"type": "state", "data": snap}))

    def _state_for(self, sess: Session, cache: dict | None = None) -> dict | None:
        """這個瀏覽器現在該收到的狀態：依它的清單視窗取快照，清單沒變就不帶 queue（所有送狀態的地方都走這裡）

        The state this browser should get now: a snapshot cut to its queue window, without ``queue`` when the list is
        unchanged. Every place that sends a state goes through here.
        """
        snap = self.hub.snapshot(sess.gid, sess.ctx, sess.pid, cache, sess.view.limit)
        return None if snap is None else sess.view.trim(snap)

    async def _send_state(self, sess: Session) -> None:
        """只送狀態給這一個瀏覽器 / Send the state to this one browser only."""
        snap = self._state_for(sess)
        if snap is not None:
            await self._safe_emit(sess, {"type": "state", "data": snap})
