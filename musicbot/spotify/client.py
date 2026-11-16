"""Spotify 官方 API 的小客戶端：授權碼 + PKCE（不需要 Client Secret）、換憑證、續期、讀自己的歌單

為什麼這樣做：Spotify 2026 年 2 月之後，開發模式的應用程式要擁有者有 Premium、最多 5 位使用者，而且只讀得到"自己建立或共同編輯"的歌單內容
PKCE 的好處是沒有祕密金鑰要保管；用戶端 id 不是祕密，寫在 .env 的 SPOTIFY_CLIENT_ID

A small client of Spotify's official API: authorisation code + PKCE (no client secret needed), token exchange, refresh, reading one's own playlists.
Why: since February 2026 a Development Mode app needs a Premium owner, allows 5 users at most, and only lets playlists the user owns or collaborates on
be read. PKCE leaves no secret to keep; the client id is not a secret (SPOTIFY_CLIENT_ID in .env).
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
from urllib.parse import parse_qs, quote, urlencode, urlparse

import aiohttp

from .. import params

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"
SCOPES = "playlist-read-private playlist-read-collaborative"      # 只讀歌單，不能改任何東西 / read playlists only; nothing can be changed


class SpotifyError(RuntimeError):
    """Spotify 回了錯誤（訊息可以直接給使用者看）/ Spotify returned an error (the message can be shown to the user)."""


def new_pkce() -> tuple[str, str]:
    """(驗證碼, 挑戰碼)：PKCE 用來證明"要換憑證的人就是當初發起授權的人"

    ``(verifier, challenge)``: PKCE proves that whoever exchanges the code is whoever started the authorisation.
    """
    verifier = secrets.token_urlsafe(64)[:100]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def auth_url(client_id: str, redirect_uri: str, state: str, challenge: str) -> str:
    """要使用者打開去授權的網址 / The address the user opens to authorise."""
    q = urlencode({"client_id": client_id, "response_type": "code", "redirect_uri": redirect_uri, "scope": SCOPES,
                   "state": state, "code_challenge_method": "S256", "code_challenge": challenge}, quote_via=quote)
    return f"{AUTH_URL}?{q}"


def parse_redirect(text: str) -> tuple[str, str]:
    """從使用者貼回來的東西取出 (code, state)：可以是整段網址，也可以只有 ?code=… 之後的部分

    Pull ``(code, state)`` out of what the user pasted back: the whole address, or just the query part after it.
    """
    raw = (text or "").strip()
    query = urlparse(raw).query or raw.lstrip("?")
    q = parse_qs(query)
    if "error" in q:
        raise SpotifyError("Spotify 沒有授權（你按了取消或拒絕）")
    code, state = (q.get("code") or [""])[0], (q.get("state") or [""])[0]
    if not code or not state:
        raise SpotifyError("貼的網址裡找不到授權碼，請把授權後瀏覽器網址列的整段網址貼進來")
    return code, state


async def _token_request(session: aiohttp.ClientSession, data: dict) -> dict:
    """向 Spotify 換憑證或續期 / Exchange or refresh tokens at Spotify."""
    try:
        async with session.post(TOKEN_URL, data=data, timeout=aiohttp.ClientTimeout(total=params.SPOTIFY_TIMEOUT)) as r:
            body = await r.json(content_type=None)
            if r.status != 200:
                raise SpotifyError(f"Spotify 拒絕了：{body.get('error_description') or body.get('error') or r.status}")
            return body
    except (aiohttp.ClientError, TimeoutError) as exc:
        raise SpotifyError(f"連不上 Spotify：{exc}") from exc


def _tokens(body: dict, old_refresh: str = "") -> dict:
    """整理成要存的樣子；續期時 Spotify 不一定回新的 refresh_token，沒有就沿用舊的 / Shape the tokens for storage; a refresh may not return a new refresh token, then the old one stays."""
    return {"access": body["access_token"], "refresh": body.get("refresh_token") or old_refresh,
            "expires": time.time() + int(body.get("expires_in", 3600)) - 30}


async def exchange(session: aiohttp.ClientSession, client_id: str, redirect_uri: str, code: str, verifier: str) -> dict:
    """授權碼換憑證 / Exchange the authorisation code for tokens."""
    body = await _token_request(session, {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
                                          "client_id": client_id, "code_verifier": verifier})
    return _tokens(body)


async def refresh(session: aiohttp.ClientSession, client_id: str, refresh_token: str) -> dict:
    """用 refresh token 換新的 access token / Get a new access token with the refresh token."""
    body = await _token_request(session, {"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": client_id})
    return _tokens(body, refresh_token)


async def get(session: aiohttp.ClientSession, access: str, path: str, **query) -> dict:
    """GET 一個 API 路徑 / GET one API path."""
    try:
        async with session.get(f"{API}{path}", params=query, headers={"Authorization": f"Bearer {access}"},
                               timeout=aiohttp.ClientTimeout(total=params.SPOTIFY_TIMEOUT)) as r:
            if r.status == 401:
                raise SpotifyError("expired")
            if r.status == 403:
                raise SpotifyError("Spotify 不讓這個帳號讀這份資料（開發模式只讀得到自己建立或共同編輯的歌單，帳號也要在應用程式的使用者名單裡）")
            if r.status == 429:
                raise SpotifyError("Spotify 要我們慢一點，請稍後再試")
            if r.status != 200:
                raise SpotifyError(f"Spotify 回了 {r.status}")
            return await r.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError) as exc:
        raise SpotifyError(f"連不上 Spotify：{exc}") from exc


def playlist_row(p: dict) -> dict:
    """一張歌單的摘要；歌數欄位在 2026 年改名（tracks -> items），兩種都吃 / A playlist summary; the count field was renamed in 2026 (tracks -> items), both are accepted."""
    count = (p.get("items") or p.get("tracks") or {}).get("total", 0)
    images = p.get("images") or []
    return {"id": p.get("id", ""), "name": p.get("name") or "", "count": int(count or 0),
            "image": (images[0].get("url") if images else "") or "", "owner": (p.get("owner") or {}).get("display_name") or ""}


def song_from_item(entry: dict) -> dict | None:
    """歌單裡的一筆 -> 我的歌單存的歌；曲目欄位在 2026 年改名（track -> item），兩種都吃；影集、本機檔、已下架的略過

    One playlist entry -> a song as the library stores it. The track field was renamed in 2026 (track -> item), both are accepted;
    episodes, local files and removed tracks are skipped.
    """
    t = (entry or {}).get("item") or (entry or {}).get("track") or {}
    if not t or t.get("type", "track") != "track" or t.get("is_local") or not t.get("id"):
        return None
    artists = ", ".join(a.get("name", "") for a in t.get("artists") or [] if a.get("name"))
    images = (t.get("album") or {}).get("images") or []
    title = t.get("name") or ""
    return {"url": f"https://open.spotify.com/track/{t['id']}", "title": f"{title} - {artists}" if artists else title,
            "duration": int((t.get("duration_ms") or 0) / 1000) or None,
            "thumbnail": (images[-2]["url"] if len(images) > 1 else images[0]["url"]) if images else "",
            "uploader": artists, "search": f"{title} {artists.split(',')[0].strip()}".strip()}


async def list_playlists(session: aiohttp.ClientSession, access: str) -> list[dict]:
    """我的歌單清單（分頁讀完）/ The user's playlists, every page."""
    out: list[dict] = []
    while len(out) < params.SPOTIFY_MAX_PLAYLISTS:
        page = await get(session, access, "/me/playlists", limit=params.SPOTIFY_PAGE, offset=len(out))
        rows = [playlist_row(p) for p in page.get("items") or [] if p]
        out.extend(rows)
        if not page.get("next") or not rows:
            break
    return out


async def playlist_songs(session: aiohttp.ClientSession, access: str, playlist_id: str) -> list[dict]:
    """一張歌單的所有歌（分頁讀完，最多 SPOTIFY_MAX_SONGS 首）/ Every song of one playlist (all pages, at most SPOTIFY_MAX_SONGS)."""
    out: list[dict] = []
    offset = 0
    while len(out) < params.SPOTIFY_MAX_SONGS:
        page = await get(session, access, f"/playlists/{quote(playlist_id, safe='')}/items", limit=100, offset=offset)
        entries = page.get("items") or []
        out.extend(s for s in map(song_from_item, entries) if s)
        offset += len(entries)
        if not page.get("next") or not entries:
            break
    return out[: params.SPOTIFY_MAX_SONGS]
