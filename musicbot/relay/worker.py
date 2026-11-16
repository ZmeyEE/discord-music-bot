"""家裡的播放端連進來：HMAC 挑戰握手，之後只轉送訊息

The home player connecting in: HMAC challenge handshake, then it only forwards messages
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import secrets

from aiohttp import WSMsgType, web

from .. import params
from .util import client_ip, proof

log = logging.getLogger("musicbot")


class WorkerMixin:
    async def worker_ws(self, request: web.Request) -> web.StreamResponse:
        """播放端的 WebSocket：先驗證 RELAY_KEY，通過後雙向轉送訊息

        The worker's WebSocket: verify RELAY_KEY first, then forward messages both ways.
        """
        who = client_ip(request)
        if self._locked(who):
            raise web.HTTPTooManyRequests(text="嘗試太多次，暫時封鎖")
        if self._handshakes.get(who, 0) >= params.MAX_HANDSHAKES_PER_IP:
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
                msg = await asyncio.wait_for(ws.receive(), params.AUTH_TIMEOUT)
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
