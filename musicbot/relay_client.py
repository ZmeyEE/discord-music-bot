"""家裡的機器人這一端：主動連到中繼站，把中繼站轉來的瀏覽器連線接到 DashboardCore

不需要在家裡開任何埠、不用管路由器；斷線會自動重連

The home side of the relay setup: the bot dials *out* to the relay and plugs the browser connections the
relay forwards into ``DashboardCore``.

No port needs to be opened at home and no router setup is required; the connection is re-established
automatically after a drop. See relay.py for the other half (the relay server itself).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

import aiohttp

from .hub import Hub
from .relay import proof
from . import params

log = logging.getLogger("musicbot.relay")



class RelayClient:
    """維持與中繼站的連線，並把每個瀏覽器工作階段轉給 DashboardCore

    Keeps the connection to the relay alive and hands every browser session to ``DashboardCore``.
    Messages from the relay look like ``{"t": "open"|"msg"|"close", "sid": <browser session id>, ...}``.
    """

    def __init__(self, hub: Hub, url: str, key: str) -> None:
        self.hub = hub
        self.url = url.rstrip("/")
        self.key = key
        self.connected = False

    @property
    def http_url(self) -> str:
        """中繼站的網頁網址（給 /help 當前綴）

        The relay's web address (ws:// -> http://, wss:// -> https://); used as the prefix of /help links.
        """
        return self.url.replace("ws://", "http://", 1).replace("wss://", "https://", 1)

    # ------------------------------------------------------------
    # 連線迴圈 / Connection loop
    # ------------------------------------------------------------
    async def run(self) -> None:
        """永遠重試連線：失敗後等待 3 秒起、每次加倍，最多 30 秒

        Reconnect forever: wait 3 s after a failure, doubling each time up to 30 s (exponential back-off).
        """
        delay, warned = 3.0, False
        while True:
            try:
                await self._once()
                delay, warned = 3.0, False         # 連上過再斷線：重新從短間隔開始 / was connected, then dropped: start again with a short delay
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                if not warned:                     # 持續連不上時只記一次，避免洗版 / log only once while it keeps failing, to avoid spam
                    log.warning("連不上中繼站 %s：%s（會持續自動重試）", self.url, exc)
                    warned = True
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30.0)

    async def _once(self) -> None:
        """一次完整連線：握手 → 收發訊息 → 斷線清理

        One full connection: handshake -> pump messages -> clean up on disconnect.
        """
        sessions: dict[str, object] = {}
        core = self.hub.core
        async with aiohttp.ClientSession() as http:
            async with http.ws_connect(f"{self.url}/relay", heartbeat=20, max_msg_size=4 * 1024 * 1024) as ws:
                # 挑戰—回應握手：中繼站給一個隨機數，我們用 RELAY_KEY 算出證明（金鑰本身不會經過網路）
                # Challenge-response handshake: the relay sends a random nonce and we answer with a proof
                # computed from RELAY_KEY (the key itself never crosses the network).
                challenge = await asyncio.wait_for(ws.receive_json(), 10)
                await ws.send_json({"t": "auth", "proof": proof(self.key, str(challenge.get("nonce", "")))})
                reply = await asyncio.wait_for(ws.receive(), 10)
                if reply.type != aiohttp.WSMsgType.TEXT or json.loads(reply.data).get("t") != "ready":
                    raise RuntimeError("中繼站拒絕了連線：RELAY_KEY 與中繼站設定的不一致")
                self.connected = True
                log.info("已連上中繼站：%s", self.url)
                hello_task = asyncio.create_task(self._hello_loop(ws))
                try:
                    async for msg in ws:
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            continue
                        await self._dispatch(ws, sessions, json.loads(msg.data))
                finally:
                    hello_task.cancel()
                    self.connected = False
                    for sess in list(sessions.values()):   # 連線斷了，所有瀏覽器工作階段一併收掉 / connection gone: close every browser session
                        core.close(sess)
                    log.info("與中繼站的連線中斷")

    # ------------------------------------------------------------
    # 心跳與狀態 / Heartbeat and status
    # ------------------------------------------------------------
    async def _hello_loop(self, ws) -> None:
        """告訴中繼站：我是哪個存取模式、有哪些伺服器（讓它能回答 /api/guilds）
        內容有變（例如 Discord 剛連上、伺服器清單出現）就立刻送，沒變就每 30 秒送一次當心跳

        Tell the relay which access mode we use and which servers we're in (so it can answer
        ``/api/guilds``). Sent immediately when something changed (e.g. Discord just connected),
        otherwise every 30 s as a heartbeat.
        """
        last, sent_at = None, 0.0
        while True:
            payload = {"t": "hello", "open": self.hub.open_access, "guilds": self.hub.guild_list()}
            if payload != last or time.monotonic() - sent_at >= params.HELLO_INTERVAL:
                await ws.send_json(payload)
                last, sent_at = payload, time.monotonic()
            await asyncio.sleep(2.0)

    # ------------------------------------------------------------
    # 訊息分派 / Message dispatch
    # ------------------------------------------------------------
    async def _dispatch(self, ws, sessions: dict, d: dict) -> None:
        """處理中繼站轉來的一則訊息：開啟、資料、關閉某個瀏覽器工作階段

        Handle one message from the relay: open, data or close for one browser session (``sid``).
        """
        core, t, sid = self.hub.core, d.get("t"), str(d.get("sid", ""))

        async def emit(msg: dict) -> None:
            """把訊息送回那個瀏覽器（經中繼站轉送） / Send a message back to that browser (forwarded by the relay)."""
            await ws.send_json({"t": "msg", "sid": sid, "data": msg})

        if t == "open":
            old = sessions.pop(sid, None)
            if old:
                core.close(old)
            gid, q = int(d.get("gid", 0)), d.get("query") or {}
            # is_local 永遠是 False：經過中繼站的連線不可能被當成"本地主人"
            # is_local is always False: a connection that came through the relay can never be treated as the local owner.
            ctx = await core.authenticate(gid, q.get("t"), q.get("n"), is_local=False, device=q.get("d"))
            if ctx is None:
                await emit({"type": "error", "code": "auth", "text": "連結無效或已過期。請在 Discord 輸入 /help 取得新的連結。"})
                await ws.send_json({"t": "close", "sid": sid})
                return
            sess = await core.open_session(gid, ctx, emit)
            if sess is None:
                await ws.send_json({"t": "close", "sid": sid})
            else:
                sessions[sid] = sess
        elif t == "msg":
            sess = sessions.get(sid)
            data = d.get("data")
            if sess is not None and isinstance(data, dict):
                await core.handle(sess, data)
        elif t == "close":
            sess = sessions.pop(sid, None)
            if sess is not None:
                core.close(sess)
