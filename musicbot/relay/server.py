"""中繼站伺服器：只轉送訊息，不放歌（不需要 discord.py、yt-dlp、ffmpeg）

The relay server: it only forwards messages and never plays audio (no discord.py, yt-dlp or ffmpeg needed)
"""
from __future__ import annotations

from collections import deque

from aiohttp import web

from ..paths import WEB_DIR
from ..webutil import secure_headers
from .browser import BrowserMixin
from .limits import LimitsMixin
from .util import Browser
from .worker import WorkerMixin


class Relay(LimitsMixin, WorkerMixin, BrowserMixin):
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
