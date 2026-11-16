"""中繼站用的小工具：挑戰回應、真實來源 IP、瀏覽器連線資料

Small helpers of the relay: challenge proof, real client IP, the browser connection record
"""
from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass, field

from aiohttp import web

from .. import params

_LOOPBACK = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}   # 本地位址：只有來自這裡的代理標頭才可信 / loopback addresses: only proxy headers from here are trusted


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
    tokens: float = params.BURST
    last: float = field(default_factory=time.monotonic)

    def allow(self) -> bool:
        """這一則訊息可以轉送嗎？額度隨時間回補，用完就丟掉

        May this message be forwarded? Allowance refills over time; when it runs out the message is dropped.
        """
        now = time.monotonic()
        self.tokens = min(params.BURST, self.tokens + (now - self.last) * params.RATE_PER_SEC)
        self.last = now
        if self.tokens < 1:
            return False
        self.tokens -= 1
        return True
