"""本機網頁伺服器：靜態檔、WebSocket 進來後交給 DashboardCore

The local web server: static files, then hands each WebSocket to DashboardCore
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from aiohttp import WSMsgType, web

from ..hub import Hub
from ..webutil import secure_headers

# 經過反向代理／通道（例如 cloudflared、ngrok）進來的請求會帶這些標頭，不能當作本地
# Requests that arrive through a reverse proxy / tunnel (cloudflared, ngrok...) carry these headers, so they must not be treated as local.
_PROXY_HEADERS = ("X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto", "Forwarded",
                  "X-Real-IP", "CF-Connecting-IP", "CF-Ray", "True-Client-IP")


_LOOPBACK = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


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
        app.router.add_get("/spotify/callback", self.spotify_callback)
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

    async def spotify_callback(self, request: web.Request) -> web.Response:
        """Spotify 授權完導回來的頁面：什麼都不處理，只告訴使用者把網址貼回看板（這樣本機和朋友的電腦流程一樣）

        The page Spotify sends the browser back to. It processes nothing and only tells the user to paste this address back into the dashboard
        (so the local machine and a friend's computer follow the same flow).
        """
        return web.Response(text="<!doctype html><meta charset=utf-8><title>Spotify</title>"
                                 "<body style=\"font-family:sans-serif;max-width:32em;margin:3em auto;padding:0 1em\">"
                                 "<h2>已經授權了 / Authorised</h2>"
                                 "<p>請把這個頁面<b>網址列的整段網址</b>複製起來，貼回音樂看板的 Spotify 視窗。</p>"
                                 "<p>Copy the <b>whole address</b> from this page's address bar and paste it back into the Spotify window of the dashboard.</p></body>",
                            content_type="text/html")

    async def guilds(self, request: web.Request) -> web.Response:
        """伺服器清單：只有本機才給 / The server list: only for the local machine."""
        if not self._is_local(request):
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
