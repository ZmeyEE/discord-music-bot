"""瀏覽器連進來：同源檢查、轉送到對應的播放端

Browsers connecting in: same-origin check, forwarded to the matching player
"""
from __future__ import annotations

import json
import uuid

from aiohttp import WSMsgType, web

from .. import params
from .util import Browser, client_ip


class BrowserMixin:
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
        if len(self.browsers) >= params.MAX_BROWSERS:
            raise web.HTTPServiceUnavailable(text="連線數已達上限")
        ip = client_ip(request)
        if not self._admit_browser(ip):
            raise web.HTTPTooManyRequests(text="連線太頻繁，請稍後再試")
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=params.MAX_MSG_BYTES)
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
