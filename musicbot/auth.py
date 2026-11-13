"""後台存取憑證：由機器人簽章、有時效、綁定伺服器與 Discord 使用者的連結憑證

使用者在 Discord 輸入 /help，機器人用"他自己的 Discord 身分"簽出一組憑證放進連結
後台收到連結就知道"這是誰"，再依他是否在語音頻道決定能不能控制，不需要 OAuth、不需要額外設定
連結等於那個人的身分，請不要轉貼別人的（/help 的回覆只有本人看得到）

Dashboard access tokens: signed by the bot, time-limited, and bound to one guild and one Discord user.

When someone types /help in Discord, the bot signs a token with *their* Discord identity and embeds it
in a link. When the dashboard receives that link it knows who is knocking, and can decide (by access
mode) whether they may control playback. No OAuth, no extra setup. A link *is* that person's identity,
so please don't forward it (the /help reply is ephemeral — only they can see it).

Token format / 憑證格式:  base64url(JSON payload) + "." + base64url(HMAC-SHA256 signature, first 18 bytes)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

DEFAULT_TTL = 12 * 3600   # 12 小時；過期後再輸入一次 /help 即可 / 12 hours; type /help again after it expires


@dataclass(frozen=True)
class Identity:
    """憑證解開後的身分 / The identity carried inside a verified token."""
    guild_id: int
    user_id: int
    name: str


# ============================================================
# 編碼小工具 / Encoding helpers
# ============================================================
def _b64(data: bytes) -> str:
    """URL 安全的 base64（去掉尾端 =） / URL-safe base64 without the trailing '=' padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    """_b64 的反向：補回 = 後解碼 / Inverse of _b64: restore the padding, then decode."""
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(secret: str, body: str) -> str:
    """用 HMAC-SHA256 簽章（取前 18 bytes，連結比較短） / HMAC-SHA256 signature, truncated to 18 bytes to keep links short."""
    return _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()[:18])


# ============================================================
# 簽發與驗證 / Issue and verify
# ============================================================
def make_token(secret: str, guild_id: int, user_id: int, name: str, ttl: int = DEFAULT_TTL) -> str:
    """簽出一組憑證，名稱最多保留 32 字

    Issue a token for (guild, user). The display name is capped at 32 characters;
    ``ttl`` is the lifetime in seconds.
    """
    payload = {"g": str(guild_id), "u": str(user_id), "n": name[:32], "e": int(time.time()) + ttl}
    body = _b64(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode())
    return f"{body}.{_sign(secret, body)}"


def verify_token(secret: str, token: str) -> Identity | None:
    """簽章正確且沒過期才回傳身分，否則 None

    Return the identity only if the signature is valid and the token has not expired; otherwise None.
    ``hmac.compare_digest`` is used so the comparison time does not leak how many characters matched.
    """
    try:
        body, sig = token.split(".", 1)
        if not hmac.compare_digest(sig, _sign(secret, body)):
            return None
        payload = json.loads(_unb64(body))
        if int(payload["e"]) < time.time():
            return None
        return Identity(int(payload["g"]), int(payload["u"]), str(payload.get("n", "")))
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None
