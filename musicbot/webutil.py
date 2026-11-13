"""看板與中繼站共用的 HTTP 安全設定（只依賴 aiohttp）

HTTP security settings shared by the dashboard and the relay (depends on aiohttp only).
Every response gets a strict Content-Security-Policy and a few other hardening headers.
"""
from __future__ import annotations

from aiohttp import web

# ============================================================
# 安全標頭 / Security headers
# ============================================================

# 內容安全政策：只允許自己的腳本；樣式允許內嵌（介面用到）與 Google Fonts；圖片允許 https（縮圖來自 Bilibili／YouTube）與 data:（QR 碼）
# Content-Security-Policy: scripts only from ourselves; styles inline (the UI needs it) plus Google Fonts;
# images over https (thumbnails come from Bilibili/YouTube) and data: URLs (QR codes).
CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src https://fonts.gstatic.com",
    "img-src 'self' data: https:",
    "connect-src 'self' ws: wss:",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",          # 不能被別的網站用 iframe 嵌進去（防點擊劫持）/ cannot be framed by other sites (anti-clickjacking)
])

SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",       # 不讓瀏覽器亂猜檔案類型 / stop MIME sniffing
    "X-Frame-Options": "DENY",                 # 舊式的防嵌入標頭 / legacy anti-framing header
    "Referrer-Policy": "no-referrer",          # 不外洩來源網址 / do not leak the referring URL
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",  # 關掉用不到的瀏覽器功能 / switch off unused browser features
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cache-Control": "no-store",               # 不快取（內含個人化資料）/ never cache (responses can be personalised)
}


# ============================================================
# 中介層 / Middleware
# ============================================================
@web.middleware
async def secure_headers(request: web.Request, handler):
    """替每個回應加上安全標頭（含錯誤回應）

    Adds the security headers to every response, including error responses.
    ``setdefault`` is used so a handler can still override a header on purpose.
    """
    try:
        resp = await handler(request)
    except web.HTTPException as exc:       # 403／429 等錯誤回應也要帶標頭 / 403/429 etc. need the headers too
        for k, v in SECURITY_HEADERS.items():
            exc.headers.setdefault(k, v)
        raise
    if not getattr(resp, "prepared", False):   # WebSocket 升級後標頭已送出，不能再改 / after a WebSocket upgrade the headers are already sent
        for k, v in SECURITY_HEADERS.items():
            resp.headers.setdefault(k, v)
    return resp
