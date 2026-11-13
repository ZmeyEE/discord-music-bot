"""中繼站（控制台節點）：給"放歌在家裡、看板放在 VPS／樹莓派"的架構

    朋友的瀏覽器 ──▶ 中繼站（有公網 IP 的 VPS／樹莓派）◀── 家裡的機器人（主動連出來）

為什麼：家裡的電腦在路由器後面，朋友連不進來；而放歌必須留在家裡（住宅 IP 才能正常搜尋 Bilibili／YouTube，
也不需要買好的主機），所以讓家裡的機器人"主動連出"到中繼站，中繼站只負責把瀏覽器與機器人之間的訊息互相轉送

這個檔案只依賴 aiohttp：**不需要 discord.py、yt-dlp、ffmpeg**，樹莓派或最便宜的 VPS 就能跑
所有權限判斷與資料都仍在家裡的機器人那邊；中繼站不保存任何東西、也看不懂訊息內容

執行：  python -m musicbot.relay        （需要環境變數／.env 的 RELAY_KEY）

Relay (control-panel node): for the setup "play music at home, host the dashboard on a VPS / Raspberry Pi".

    friend's browser ──▶ relay (VPS / Pi with a public IP) ◀── bot at home (dials out)

Why: a home PC sits behind a router that friends can't reach, yet playback must stay at home (a residential
IP is what lets Bilibili / YouTube searches work normally, and you don't need a beefy server). So the bot at
home dials *out* to the relay, and the relay only forwards messages between browsers and the bot.

This file depends on aiohttp only: **no discord.py, yt-dlp or ffmpeg needed**, so a Raspberry Pi or the
cheapest VPS can run it. All permission checks and all data stay with the bot at home; the relay stores
nothing and cannot interpret the messages.

Run:  python -m musicbot.relay     (needs ``RELAY_KEY`` in the environment or .env)

Defences built in / 內建防護:
  * challenge-response handshake with RELAY_KEY (the key never travels over the network)
  * per-IP caps on simultaneous browsers, new connections per minute and unfinished handshakes
  * temporary lock-out after repeated failed handshakes
  * per-browser message rate limit, message size limit, same-origin check on WebSockets
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import uuid
from collections import deque
from dataclasses import dataclass, field

from aiohttp import WSMsgType, web

from . import config
from .paths import LOG_DIR, WEB_DIR
from .webutil import secure_headers

log = logging.getLogger("musicbot.relay")

# ============================================================
# 限制參數 / Limits
# ============================================================
MAX_BROWSERS = 300           # 同時連線的瀏覽器上限 / max simultaneous browsers
MAX_PER_IP = 12              # 同一個來源 IP 同時最多幾個瀏覽器連線（避免一個人把名額占滿）/ max simultaneous browsers per source IP (stops one person hogging all slots)
NEW_PER_MINUTE = 40          # 同一個來源 IP 每分鐘最多幾次新連線（擋掃描與灌連線）/ max new connections per IP per minute (blocks scans and floods)
MAX_MSG_BYTES = 64 * 1024    # 瀏覽器單則訊息大小上限 / max size of one browser message
RATE_PER_SEC = 25            # 每個瀏覽器每秒最多轉送幾則（超過的丟掉，保護家裡的機器人）/ messages forwarded per browser per second (extra ones are dropped to protect the home bot)
BURST = 60                   # 瞬間可累積的額度（token bucket 容量）/ burst allowance (token-bucket capacity)
AUTH_TIMEOUT = 10.0          # 握手最多等幾秒 / seconds to wait for the handshake answer
MAX_HANDSHAKES_PER_IP = 3    # 同一個來源 IP 同時最多幾個"還沒完成握手"的播放端連線 / max unfinished worker handshakes per IP
AUTH_FAIL_LIMIT = 5          # 同一個來源 IP 在視窗內握手失敗幾次就封鎖 / failed handshakes within the window before the IP is locked out
AUTH_FAIL_WINDOW = 600.0     # 計算失敗次數的時間視窗（秒）/ window (s) over which failures are counted
AUTH_LOCKOUT = 600.0         # 封鎖多久（秒）/ lock-out duration (s)
_LOOPBACK = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}   # 本地位址：只有來自這裡的代理標頭才可信 / loopback addresses: only proxy headers from here are trusted


# ============================================================
# 小工具 / Helpers
# ============================================================
def proof(key: str, nonce: str) -> str:
    """握手證明：HMAC-SHA256(金鑰, 隨機挑戰)，金鑰本身不會在網路上傳送

    Handshake proof: HMAC-SHA256(key, random challenge). The key itself is never sent over the network.
    """
    return hmac.new(key.encode(), nonce.encode(), hashlib.sha256).hexdigest()


def client_ip(request: web.Request) -> str:
    """真正的來源 IP，只有"直接連到我的是本地（代理／通道，例如 cloudflared）"時才相信代理標頭，
    直接從網際網路連進來的人無法用標頭偽造自己的 IP

    The real source IP. Proxy headers (``CF-Connecting-IP`` / ``X-Forwarded-For``) are trusted only when the
    direct peer is this machine itself (a local reverse proxy or tunnel such as cloudflared); someone
    connecting straight from the internet cannot spoof their IP with a header.
    """
    peer = request.remote or "?"
    if peer in _LOOPBACK:
        for h in ("CF-Connecting-IP", "X-Forwarded-For"):
            v = request.headers.get(h)
            if v:
                return v.split(",")[0].strip()[:64]
    return peer


@dataclass(eq=False)
class Browser:
    """一個連到中繼站的瀏覽器，附帶簡單的限速器（token bucket）

    One browser connected to the relay, with a small rate limiter (token bucket).
    ``query`` keeps the link parameters (t = signed token, n = nickname, d = device token) to pass to the bot.
    """
    ws: web.WebSocketResponse
    sid: str
    gid: int
    query: dict
    tokens: float = BURST
    last: float = field(default_factory=time.monotonic)

    def allow(self) -> bool:
        """這一則訊息可以轉送嗎？額度隨時間回補，用完就丟掉

        May this message be forwarded? Allowance refills over time; when it runs out the message is dropped.
        """
        now = time.monotonic()
        self.tokens = min(BURST, self.tokens + (now - self.last) * RATE_PER_SEC)
        self.last = now
        if self.tokens < 1:
            return False
        self.tokens -= 1
        return True


# ============================================================
# 中繼站本體 / The relay itself
# ============================================================
class Relay:
    """HTTP + WebSocket 伺服器：一邊接瀏覽器，一邊接家裡的播放端（worker），兩邊互相轉送訊息

    HTTP + WebSocket server. Browsers connect on ``/ws/<guild id>``; the home bot ("worker") connects on
    ``/relay``. Messages are forwarded verbatim in both directions. Only one worker is kept at a time.
    """

    def __init__(self, key: str, host: str, port: int) -> None:
        self.key, self.host, self.port = key, host, port
        self.worker: web.WebSocketResponse | None = None      # 目前連著的播放端 / the currently connected home bot
        self.hello: dict = {"open": False, "guilds": []}      # 播放端最近一次回報的狀態 / last status reported by the worker
        self.browsers: dict[str, Browser] = {}
        self._runner: web.AppRunner | None = None
        # 每個來源 IP 的限制（見檔案開頭的常數）/ per-source-IP bookkeeping (see the constants above)
        self._per_ip: dict[str, int] = {}
        self._new_conns: dict[str, deque] = {}
        self._handshakes: dict[str, int] = {}
        self._auth_fails: dict[str, list] = {}
        self._locked_until: dict[str, float] = {}

    # ------------------------------------------------------------
    # 來源 IP 限制 / Per-IP limits
    # ------------------------------------------------------------
    def _admit_browser(self, ip: str) -> bool:
        """這個 IP 還可以再開一個瀏覽器連線嗎？（同時數 + 每分鐘新連線數）

        May this IP open another browser connection? (Checks both concurrent count and new-per-minute rate.)
        """
        now = time.monotonic()
        hist = self._new_conns.setdefault(ip, deque())
        while hist and now - hist[0] > 60:
            hist.popleft()
        if len(hist) >= NEW_PER_MINUTE or self._per_ip.get(ip, 0) >= MAX_PER_IP:
            return False
        hist.append(now)
        self._per_ip[ip] = self._per_ip.get(ip, 0) + 1
        return True

    def _release_browser(self, ip: str) -> None:
        """瀏覽器離線時歸還名額 / Give the slot back when a browser disconnects."""
        n = self._per_ip.get(ip, 0) - 1
        if n > 0:
            self._per_ip[ip] = n
        else:
            self._per_ip.pop(ip, None)
        if not self._new_conns.get(ip):
            self._new_conns.pop(ip, None)

    def _locked(self, ip: str) -> bool:
        """這個 IP 目前被封鎖嗎？封鎖到期會自動解除 / Is this IP currently locked out? Expired lock-outs are lifted automatically."""
        until = self._locked_until.get(ip, 0.0)
        if until and time.monotonic() >= until:
            self._locked_until.pop(ip, None)
            self._auth_fails.pop(ip, None)
            return False
        return bool(until)

    def _record_auth_failure(self, ip: str) -> None:
        """記一次握手失敗；視窗內達上限就封鎖 / Record a failed handshake; lock the IP out once the limit is hit within the window."""
        now = time.monotonic()
        fails = [t for t in self._auth_fails.get(ip, []) if now - t < AUTH_FAIL_WINDOW] + [now]
        self._auth_fails[ip] = fails
        if len(fails) >= AUTH_FAIL_LIMIT:
            self._locked_until[ip] = now + AUTH_LOCKOUT
            log.warning("來源 %s 握手失敗 %d 次，封鎖 %d 分鐘", ip, len(fails), int(AUTH_LOCKOUT // 60))

    # ------------------------------------------------------------
    # 啟動／關閉 / Start and stop
    # ------------------------------------------------------------
    async def start(self) -> None:
        """註冊路由並開始監聽 / Register the routes and start listening."""
        app = web.Application(middlewares=[secure_headers])
        app.router.add_get("/", self.index)
        app.router.add_get("/g/{gid:\\d+}", self.index)
        app.router.add_get("/api/guilds", self.guilds)
        app.router.add_get("/healthz", self.healthz)
        app.router.add_get("/ws/{gid:\\d+}", self.browser_ws)
        app.router.add_get("/relay", self.worker_ws)
        app.router.add_static("/static/", WEB_DIR, follow_symlinks=False)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        await web.TCPSite(self._runner, self.host, self.port).start()

    async def stop(self) -> None:
        """關閉所有連線與伺服器 / Close every connection and the server."""
        for b in list(self.browsers.values()):
            await b.ws.close()
        if self.worker and not self.worker.closed:
            await self.worker.close()
        if self._runner:
            await self._runner.cleanup()

    # ------------------------------------------------------------
    # 一般路由 / Plain HTTP routes
    # ------------------------------------------------------------
    async def index(self, request: web.Request) -> web.StreamResponse:
        """看板網頁（單頁應用，前端自己看網址） / The dashboard page (a single-page app; the front-end reads the URL itself)."""
        return web.FileResponse(WEB_DIR / "index.html")

    async def guilds(self, request: web.Request) -> web.Response:
        """伺服器清單，僅在 open 模式公開；其他模式拒絕，避免陌生人探測有哪些伺服器

        The server list. Only exposed in "open" mode; refused otherwise so strangers can't probe which servers exist.
        """
        if self.worker is None:
            return web.json_response([])
        if not self.hello.get("open"):
            raise web.HTTPForbidden(text="這個機器人使用語音模式，請從 Discord 的 /help 取得連結")
        return web.json_response(self.hello.get("guilds", []))

    async def healthz(self, request: web.Request) -> web.Response:
        """健康檢查：只回報播放端在不在線與瀏覽器數量，不含任何機密

        Health check: reports only whether the worker is online and the browser count. No secrets.
        """
        return web.json_response({"worker_online": self.worker is not None, "browsers": len(self.browsers)})

    # ------------------------------------------------------------
    # 家裡的機器人連進來 / The home bot connects in
    # ------------------------------------------------------------
    async def worker_ws(self, request: web.Request) -> web.StreamResponse:
        """播放端的 WebSocket：先驗證 RELAY_KEY，通過後雙向轉送訊息

        The worker's WebSocket: verify RELAY_KEY first, then forward messages both ways.
        """
        who = client_ip(request)
        if self._locked(who):
            raise web.HTTPTooManyRequests(text="嘗試太多次，暫時封鎖")
        if self._handshakes.get(who, 0) >= MAX_HANDSHAKES_PER_IP:
            raise web.HTTPTooManyRequests(text="同時握手的連線太多")
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=4 * 1024 * 1024)
        await ws.prepare(request)

        # 挑戰—回應：證明對方知道 RELAY_KEY，而不必把金鑰送過網路
        # Challenge-response: prove the peer knows RELAY_KEY without sending the key over the network.
        self._handshakes[who] = self._handshakes.get(who, 0) + 1
        try:
            nonce = secrets.token_hex(16)
            await ws.send_json({"t": "challenge", "nonce": nonce})
            try:
                msg = await asyncio.wait_for(ws.receive(), AUTH_TIMEOUT)
                data = json.loads(msg.data) if msg.type == WSMsgType.TEXT else {}
            except (asyncio.TimeoutError, ValueError):
                data = {}
        finally:
            n = self._handshakes.get(who, 1) - 1
            if n > 0:
                self._handshakes[who] = n
            else:
                self._handshakes.pop(who, None)
        if not hmac.compare_digest(str(data.get("proof", "")), proof(self.key, nonce)):
            log.warning("拒絕一個金鑰不符的連線（%s）", who)
            self._record_auth_failure(who)
            await asyncio.sleep(1.0)               # 拖慢暴力嘗試 / slow down brute-force attempts
            await ws.close(code=4401, message=b"bad key")
            return ws
        self._auth_fails.pop(who, None)

        if self.worker is not None and not self.worker.closed:
            await self.worker.close(code=4000, message=b"replaced")   # 同一時間只留一個播放端 / keep only one worker at a time
        self.worker = ws
        await ws.send_json({"t": "ready"})
        log.info("播放端已連線（%s）", who)
        for b in list(self.browsers.values()):      # 已經連著的瀏覽器，重新在新的播放端開工作階段 / browsers already connected get a fresh session on the new worker
            await self._open_on_worker(b)

        try:
            async for m in ws:
                if m.type != WSMsgType.TEXT:
                    continue
                try:
                    d = json.loads(m.data)
                except ValueError:
                    continue
                t = d.get("t")
                if t == "hello":
                    self.hello = {"open": bool(d.get("open")), "guilds": list(d.get("guilds") or [])}
                elif t in ("msg", "close"):
                    b = self.browsers.get(str(d.get("sid")))
                    if b and not b.ws.closed:
                        if t == "msg":
                            await b.ws.send_str(json.dumps(d.get("data")))
                        else:
                            await b.ws.close()
        finally:
            if self.worker is ws:
                self.worker = None
                log.info("播放端離線")
                for b in list(self.browsers.values()):
                    await self._notify_offline(b)
        return ws

    # ------------------------------------------------------------
    # 瀏覽器連進來 / Browsers connect in
    # ------------------------------------------------------------
    @staticmethod
    def _same_origin(request: web.Request) -> bool:
        """WebSocket 的 Origin 必須與網址同源，擋掉別的網站偷開連線（CSWSH）

        The WebSocket's Origin must match the page's host, which blocks other websites from opening
        connections on a visitor's behalf (cross-site WebSocket hijacking).
        """
        from urllib.parse import urlparse
        origin = request.headers.get("Origin")
        return origin is None or urlparse(origin).netloc == request.host

    async def browser_ws(self, request: web.Request) -> web.StreamResponse:
        """瀏覽器的 WebSocket：檢查來源與限額後，把訊息轉給家裡的播放端

        A browser's WebSocket: after origin and quota checks, forward its messages to the home worker.
        """
        if not self._same_origin(request):
            raise web.HTTPForbidden(text="cross-origin websocket refused")
        if len(self.browsers) >= MAX_BROWSERS:
            raise web.HTTPServiceUnavailable(text="連線數已達上限")
        ip = client_ip(request)
        if not self._admit_browser(ip):
            raise web.HTTPTooManyRequests(text="連線太頻繁，請稍後再試")
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=MAX_MSG_BYTES)
        await ws.prepare(request)
        b = Browser(
            ws, uuid.uuid4().hex[:12], int(request.match_info["gid"]),
            {"t": request.query.get("t", "")[:512] or None, "n": request.query.get("n", "")[:32] or None,
             "d": request.query.get("d", "")[:128] or None},   # 參數長度都有上限 / every parameter is length-capped
        )
        self.browsers[b.sid] = b
        try:
            if self.worker is None:
                await self._notify_offline(b)
            else:
                await self._open_on_worker(b)
            async for m in ws:
                if m.type != WSMsgType.TEXT:
                    continue
                if not b.allow():
                    continue                       # 太頻繁：丟掉，不轉給家裡的機器人 / too frequent: drop it instead of forwarding to the home bot
                try:
                    data = json.loads(m.data)
                except ValueError:
                    continue
                if not isinstance(data, dict) or not isinstance(data.get("type"), str):
                    continue
                if self.worker is None:
                    await self._notify_offline(b)
                else:
                    await self.worker.send_json({"t": "msg", "sid": b.sid, "data": data})
        finally:
            self.browsers.pop(b.sid, None)
            self._release_browser(ip)
            if self.worker is not None and not self.worker.closed:
                try:
                    await self.worker.send_json({"t": "close", "sid": b.sid})
                except ConnectionError:
                    pass
        return ws

    async def _open_on_worker(self, b: Browser) -> None:
        """通知播放端：有一個新的瀏覽器工作階段 / Tell the worker that a new browser session exists."""
        if self.worker is not None and not self.worker.closed:
            await self.worker.send_json({"t": "open", "sid": b.sid, "gid": b.gid, "query": b.query})

    @staticmethod
    async def _notify_offline(b: Browser) -> None:
        """告訴瀏覽器：播放端目前不在線 / Tell a browser that the home bot is currently offline."""
        if not b.ws.closed:
            await b.ws.send_json({"type": "error", "code": "offline",
                                  "text": "家裡的機器人目前沒有連上中繼站（可能關機或斷線），連上後會自動恢復"})


# ============================================================
# 進入點 / Entry point
# ============================================================
def main() -> None:
    """啟動中繼站（python -m musicbot.relay） / Start the relay (``python -m musicbot.relay``)."""
    config.load_env()
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    key = os.environ.get("RELAY_KEY", "").strip()
    if len(key) < 16:
        raise SystemExit(
            "請在 .env 設定 RELAY_KEY（至少 16 個字元的隨機字串）。家裡的機器人要用同一把金鑰才連得進來。\n"
            '產生方式：python -c "import secrets; print(secrets.token_hex(32))"'
        )
    host = os.environ.get("RELAY_HOST", "0.0.0.0").strip() or "0.0.0.0"
    port = config.env_int("RELAY_PORT", 8765)

    async def run() -> None:
        relay = Relay(key, host, port)
        try:
            await relay.start()
        except OSError as exc:
            raise SystemExit(f"無法啟動中繼站：連接埠 {port} 已被占用（{exc.strerror or exc}）。") from exc
        log.info("中繼站已啟動：監聽 %s:%d（等待家裡的機器人用 RELAY_URL 連進來）", host, port)
        try:
            await asyncio.Event().wait()
        finally:
            await relay.stop()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
