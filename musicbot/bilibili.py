"""Bilibili 帳號：官方 QR 掃碼登入、帳號資訊、登入狀態記憶

登入流程是 Bilibili 網頁版自己使用的官方 API（掃碼 → App 確認 → 取得登入 cookie）
機器人只儲存"登入後的 cookie"到 cookies.txt（Netscape 格式，yt-dlp 讀取），絕不接觸帳號密碼
cookie 等同登入憑證：已列入 .gitignore，請勿分享
登入是選用的：登入大會員帳號可用無損音源（Hi-Res），也比較不會被限流

Bilibili account: official QR-code login, account info and remembered login state.

The login flow uses the same official API as Bilibili's own web page (scan QR -> confirm in the app ->
receive the login cookies). The bot only stores the *resulting cookies* in ``cookies.txt`` (Netscape format,
read by yt-dlp) and never sees your password. Those cookies are equivalent to a login: they are listed in
.gitignore, please never share them. Logging in is optional: a premium (大會員) account unlocks lossless
Hi-Res audio, and any login lowers the chance of being rate-limited.
"""
from __future__ import annotations

import logging
import time
from urllib.parse import parse_qs, quote, urlparse

import aiohttp
import segno

from . import config
from .paths import COOKIE_FILE

log = logging.getLogger("musicbot")

# ============================================================
# 常數 / Constants
# ============================================================
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
}
_QR_GENERATE = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"   # 申請 QR 碼 / request a QR code
_QR_POLL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"           # 查詢掃碼狀態 / poll the scan status
_NAV = "https://api.bilibili.com/x/web-interface/nav"                                  # 查詢目前登入帳號 / who am I?
_COOKIE_NAMES = ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid")     # 只保留登入需要的 cookie / only the cookies that matter for login

# poll 回傳的狀態碼 / status codes returned by the poll endpoint
CODE_OK, CODE_EXPIRED, CODE_SCANNED, CODE_WAITING = 0, 86038, 86090, 86101
QR_LIFETIME = 180   # 秒；QR 碼的有效時間（Bilibili 約 3 分鐘）/ seconds a QR code stays valid (about 3 minutes)


class BiliError(Exception):
    """Bilibili 登入相關錯誤（訊息可直接顯示給使用者）

    Login-related error; the message is written to be shown to the user as-is.
    """


# ============================================================
# HTTP 小工具 / HTTP helpers
# ============================================================
def _client() -> aiohttp.ClientSession:
    """建立帶預設標頭與 15 秒逾時的連線 / A session with browser-like headers and a 15 s timeout."""
    return aiohttp.ClientSession(headers=_HEADERS, timeout=aiohttp.ClientTimeout(total=15))


async def _get_json(session: aiohttp.ClientSession, url: str, **kw) -> tuple[dict, aiohttp.ClientResponse]:
    """GET 並解析 JSON；把常見失敗轉成好懂的 BiliError

    GET a URL and parse the JSON; common failures (HTTP 412 rate limit, other statuses, network errors)
    are turned into friendly ``BiliError`` messages.
    """
    try:
        async with session.get(url, **kw) as resp:
            if resp.status == 412:
                raise BiliError("Bilibili 暫時限制了這個請求（HTTP 412），請稍後再試。")
            if resp.status != 200:
                raise BiliError(f"Bilibili 回應異常（HTTP {resp.status}）。")
            return await resp.json(content_type=None), resp
    except aiohttp.ClientError as exc:
        raise BiliError(f"連不上 Bilibili：{exc}") from exc


# ============================================================
# QR 登入 / QR-code login
# ============================================================
async def qr_generate() -> tuple[str, str]:
    """產生登入 QR，回傳 (要編成 QR 碼的網址, qrcode_key)

    Ask Bilibili for a fresh login QR. Returns ``(url to encode into the QR image, qrcode_key)``;
    keep the key to poll the scan status afterwards.
    """
    async with _client() as s:
        data, _ = await _get_json(s, _QR_GENERATE)
    if data.get("code") != 0:
        raise BiliError(f"無法產生登入 QR 碼：{data.get('message')}")
    return data["data"]["url"], data["data"]["qrcode_key"]


def qr_image(url: str) -> str:
    """把網址編成 QR 碼 SVG 的 data URI，前端直接放進 <img>

    Encode a URL as a QR-code SVG data URI that the front-end can drop straight into an ``<img>``.
    """
    return segno.make(url, error="m").svg_data_uri(scale=6, border=2, dark="#33405E", light="#FFFFFF")


async def qr_poll(key: str) -> tuple[int, dict | None]:
    """查詢掃碼狀態，回傳 (狀態碼, 登入成功時的 cookie 字典)

    Poll the scan status. Returns ``(status code, cookie dict)``; the cookie dict is only present
    once the login succeeded (``CODE_OK``).
    """
    async with _client() as s:
        data, resp = await _get_json(s, _QR_POLL, params={"qrcode_key": key})
        inner = data.get("data") or {}
        code = int(inner.get("code", -1))
        if code != CODE_OK:
            return code, None
        cookies = {k: v.value for k, v in resp.cookies.items() if k in _COOKIE_NAMES}
    # 備援：Set-Cookie 沒拿到的欄位，從回傳的 url 查詢字串補（要重新做 URL 編碼）
    # Fallback: fields missing from Set-Cookie are filled from the returned url's query string (re-quoted).
    qs = parse_qs(urlparse(inner.get("url", "")).query)
    for name in _COOKIE_NAMES:
        if name not in cookies and qs.get(name):
            cookies[name] = quote(qs[name][0], safe="*")
    if "SESSDATA" not in cookies:
        raise BiliError("登入成功，但沒有取得登入憑證（SESSDATA）。")
    return code, cookies


# ============================================================
# Cookie 檔 / Cookie file
# ============================================================
def save_cookies(cookies: dict) -> None:
    """寫成 Netscape 格式的 cookies.txt（yt-dlp 讀取）

    Write the cookies as a Netscape-format ``cookies.txt`` (what yt-dlp reads). Each line is
    ``domain  include-subdomains  path  secure  expiry  name  value`` separated by tabs.
    """
    expires = int(time.time()) + 180 * 24 * 3600
    lines = ["# Netscape HTTP Cookie File", "# 由 Bilibili QR 登入產生。內含登入憑證，請勿分享。"]
    for name, value in cookies.items():
        lines.append(f".bilibili.com\tTRUE\t/\tTRUE\t{expires}\t{name}\t{value}")
    COOKIE_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _cookie_header() -> str:
    """從 cookies.txt 組出 Cookie 標頭（只取登入相關欄位）

    Build a ``Cookie:`` header from cookies.txt (login-related fields only).
    """
    pairs = []
    try:
        for line in COOKIE_FILE.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) >= 7 and parts[5] in _COOKIE_NAMES:
                pairs.append(f"{parts[5]}={parts[6]}")
    except OSError:
        pass
    return "; ".join(pairs)


# ============================================================
# 帳號資訊 / Account info
# ============================================================
async def fetch_account() -> dict | None:
    """用 cookies.txt 查詢目前登入的帳號，沒登入、或 cookie 已失效回傳 None

    Look up the currently logged-in account using cookies.txt.
    Returns None when not logged in or when the cookies have expired.
    """
    header = _cookie_header()
    if not header:
        return None
    async with _client() as s:
        data, _ = await _get_json(s, _NAV, headers={"Cookie": header})
    info = data.get("data") or {}
    if not info.get("isLogin"):
        return None
    vip = bool(info.get("vipStatus"))
    return {
        "mid": str(info.get("mid", "")),
        "name": info.get("uname") or "",
        "face": info.get("face") or "",
        "vip": vip,
        "vip_label": (info.get("vip_label") or {}).get("text") or ("大會員" if vip else "一般會員"),
    }


def remember_account(account: dict | None) -> None:
    """把帳號顯示資訊存進 settings.json（None = 清除） / Save the account's display info in settings.json (None clears it)."""
    config.set_setting("bili_account", account)


def remembered_account() -> dict | None:
    """讀取記住的帳號；cookies.txt 不在了就視為沒登入 / Read the remembered account; no cookies.txt means "not logged in"."""
    acc = config.get_setting("bili_account")
    return acc if isinstance(acc, dict) and COOKIE_FILE.exists() else None


def logout() -> None:
    """登出：刪除 cookies.txt 並清除記憶的帳號資訊

    Log out: delete cookies.txt and forget the remembered account info.
    """
    try:
        COOKIE_FILE.unlink()
    except OSError:
        pass
    remember_account(None)
