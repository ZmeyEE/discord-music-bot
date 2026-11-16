"""紀錄設定：bot.log 與 voice-debug.log，寫進去之前遮蔽權杖和金鑰

Logging set-up: bot.log and voice-debug.log, with tokens and keys masked before anything is written
"""
from __future__ import annotations

import logging
import os
import re
from logging.handlers import RotatingFileHandler

from .paths import LOG_DIR


class _RedactSecrets(logging.Filter):
    """寫進除錯記錄前，遮蔽語音閘道訊息中的權杖與加密金鑰

    Log filter that masks tokens and encryption keys found in voice-gateway messages
    before they are written to the debug log, so the log file is safe to share.
    """

    _PATTERNS = (
        (re.compile(r"('token':\s*')[^']*"), r"\1***"),
        (re.compile(r"('secret_key':\s*\[)[^\]]*"), r"\1***"),
    )

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for pattern, repl in self._PATTERNS:
            msg = pattern.sub(repl, msg)
        record.msg, record.args = msg[:600], ()   # 同時截短，避免單行過長 / also truncate overly long lines
        return True


def setup_logging() -> None:
    """設定紀錄：畫面 + logs/bot.log（輪替）；VOICE_DEBUG=1 時另寫詳細的語音除錯記錄

    Configure logging: console + a rotating ``logs/bot.log``. With ``VOICE_DEBUG=1`` an extra, verbose
    ``logs/voice-debug.log`` captures the voice handshake (secrets are redacted).
    """
    LOG_DIR.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handlers = [
        logging.StreamHandler(),
        RotatingFileHandler(LOG_DIR / "bot.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8"),
    ]
    for h in handlers:
        h.setLevel(logging.INFO)
        h.setFormatter(fmt)
    logging.basicConfig(level=logging.INFO, handlers=handlers)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)   # 不記每一個 HTTP 請求 / don't log every HTTP request

    if os.environ.get("VOICE_DEBUG", "").strip() in ("1", "true", "yes"):
        # 詳細的語音／端對端加密（DAVE）握手記錄，排查"沒聲音"用，權杖與金鑰會被遮蔽
        # Verbose voice / end-to-end-encryption (DAVE) handshake log for debugging "no sound". Secrets are masked.
        dbg = RotatingFileHandler(LOG_DIR / "voice-debug.log", maxBytes=2_000_000, backupCount=1, encoding="utf-8")
        dbg.setFormatter(fmt)
        dbg.addFilter(_RedactSecrets())
        for name in ("discord.gateway", "discord.voice_state", "discord.voice_client"):
            lg = logging.getLogger(name)
            lg.setLevel(logging.DEBUG)
            lg.addHandler(dbg)
