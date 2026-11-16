"""Spotify：只讀公開嵌入頁的歌名和歌手，不碰 Spotify 音訊

Spotify: reads title and artists from the public embed page only, never Spotify audio
"""
from __future__ import annotations

import json
import re
import urllib.request

from .. import params
from .tracks import BILI_HEADERS, Track, to_https

# Spotify 的音訊有 DRM，沒辦法直接播
# 這裡只讀公開嵌入頁（不用金鑰、不用登入）拿歌名和歌手，播放前再去 Bilibili／YouTube 找對應的歌
# Spotify audio is DRM protected, so it can't be played directly.
# We only read the public embed page (no key, no login) for title and artists, then search the match on Bilibili / YouTube right before playing.
_SPOTIFY_UA = BILI_HEADERS["User-Agent"]

_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)


def _spotify_entity(kind: str, sid: str) -> dict:
    """抓嵌入頁並取出那段 JSON / Fetch the embed page and pull out its JSON."""
    req = urllib.request.Request(
        f"https://open.spotify.com/embed/{kind}/{sid}", headers={"User-Agent": _SPOTIFY_UA, "Accept-Language": "en"}
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:   # nosec B310 - 固定的 https 網址，kind／sid 已用正規表示式限制成英數字 / a fixed https URL, kind and sid are limited to alphanumerics by the regex
            html = resp.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"讀不到這個 Spotify 連結（要是公開的）：{str(exc)[:80]}") from exc
    m = _NEXT_DATA_RE.search(html)
    if not m:
        raise RuntimeError("Spotify 頁面格式變了或連結不是公開的，讀不到歌曲資訊")
    try:
        return json.loads(m.group(1))["props"]["pageProps"]["state"]["data"]["entity"]
    except (KeyError, ValueError) as exc:
        raise RuntimeError("Spotify 頁面格式變了，讀不到歌曲資訊") from exc


def _spotify_cover(ent: dict) -> str:
    """封面：挑夠用的最小一張 / Cover art: the smallest one that is big enough."""
    cands = [i for i in (ent.get("visualIdentity") or {}).get("image") or [] if isinstance(i, dict) and i.get("url")]
    if not cands:
        return ""
    big = [i for i in cands if (i.get("maxWidth") or 0) >= 300]
    best = min(big, key=lambda i: i["maxWidth"]) if big else max(cands, key=lambda i: i.get("maxWidth") or 0)
    return to_https(best["url"])


def _spotify_track(title: str, artists: str, ms: int | None, sid: str, cover: str, requester: str) -> Track:
    """一首 Spotify 歌 -> Track（url 是 Spotify 連結，search 是之後要去找對應影片的關鍵字）
    One Spotify song -> a Track (``url`` is the Spotify link, ``search`` is what we look up later)."""
    return Track(
        url=f"https://open.spotify.com/track/{sid}",
        title=f"{title} - {artists}" if artists else title,
        requester=requester,
        thumbnail=cover,
        duration=round(ms / 1000) if ms else None,
        uploader=artists,
        search=f"{title} {artists.split(',')[0].strip()}".strip(),
    )


def resolve_spotify(kind: str, sid: str, requester: str) -> list[Track]:
    """Spotify 單曲／專輯／播放清單 -> 曲目清單

    Spotify track / album / playlist -> a list of Tracks. The public embed page lists at most 100 songs of
    a playlist, so a bigger one comes back cut at 100 (checked on a 150-song playlist).
    """
    ent = _spotify_entity(kind, sid)
    cover = _spotify_cover(ent) if kind != "playlist" else ""   # 播放清單的封面不是每首的，留空，播放時用對應影片的縮圖 / a playlist cover isn't each song's: leave empty, the matched video's thumbnail is used at play time
    if kind == "track":
        artists = ", ".join(a.get("name", "") for a in ent.get("artists") or [] if a.get("name"))
        return [_spotify_track(ent.get("name") or ent.get("title") or "", artists, ent.get("duration"), sid, cover, requester)]
    tracks = []
    for item in ent.get("trackList") or []:
        m = re.match(r"spotify:track:([0-9A-Za-z]{22})$", item.get("uri") or "")
        if m and item.get("title") and item.get("isPlayable", True):
            tracks.append(_spotify_track(item["title"], item.get("subtitle") or "", item.get("duration"), m.group(1), cover, requester))
    if not tracks:
        raise RuntimeError("這個 Spotify 清單讀不到任何歌（要是公開的，且不是 Spotify 自己做的個人化清單）")
    return tracks[:params.MAX_PLAYLIST]
