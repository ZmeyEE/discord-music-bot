"""啟動入口：讀 .env、啟動中繼站

Entry point: read .env and start the relay
"""
from __future__ import annotations

import asyncio
import logging
import os

from .. import config
from ..paths import LOG_DIR
from .server import Relay

log = logging.getLogger("musicbot")

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
