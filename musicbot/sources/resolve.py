"""曲目解析：把輸入變成待播清單（不取串流網址），並補縮圖標題

Resolving tracks: turn the input into queue entries (no stream URL yet) and fill thumbnails and titles
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import replace

import yt_dlp

from .. import params
from .recognize import _SPOTIFY_RE, normalize_query
from .spotify import resolve_spotify
from .tracks import Track, _base_opts, to_https

log = logging.getLogger("musicbot")

def pick_thumb(info: dict, want: int = 480) -> str:
    """從 yt-dlp 的縮圖清單挑"寬度剛好夠用"的那張（>= want 中最小的），而不是動輒 1920px 的原圖

    Choose a thumbnail that is "just big enough" (the smallest one at least ``want`` px wide) from
    yt-dlp's list, instead of the huge 1920 px original. Saves bandwidth and keeps the UI snappy.
    """
    cands = [t for t in (info.get("thumbnails") or []) if t.get("url") and t.get("width")]
    if cands:
        big_enough = [t for t in cands if t["width"] >= want]
        best = min(big_enough, key=lambda t: t["width"]) if big_enough else max(cands, key=lambda t: t["width"])
        return to_https(best["url"])
    return to_https(info.get("thumbnail") or "")


def _track_from_info(info: dict, fallback_url: str, requester: str) -> Track:
    """把 yt-dlp 的資訊字典轉成 Track / Convert a yt-dlp info dict into a Track."""
    return Track(
        url=info.get("webpage_url") or fallback_url,
        title=info.get("title") or "",
        requester=requester,
        thumbnail=pick_thumb(info),
        duration=int(info["duration"]) if info.get("duration") else None,
        uploader=info.get("uploader") or "",
    )


_SEARCH_CACHE: dict[str, tuple[float, list[Track]]] = {}   # 關鍵字 -> (時間, 結果) / query -> (time, result)


def clear_search_cache() -> None:
    """清空搜尋快取（例如更換 Bilibili 帳號後） / Empty the search cache (e.g. after switching Bilibili account)."""
    _SEARCH_CACHE.clear()


def resolve_tracks(query: str, requester: str) -> list[Track]:
    """把使用者輸入轉成待播清單（不取串流網址，播放前才取，避免連結過期）

    Turn the user's input into a list of queue entries. Stream URLs are NOT fetched here (only right
    before playback) so they can't expire while waiting in the queue. Search results are cached briefly;
    each returned Track gets a fresh id so the same song can be queued twice.
    """
    target = normalize_query(query)
    spotify = _SPOTIFY_RE.match(target)
    if spotify:
        return resolve_spotify(spotify.group(1).lower(), spotify.group(2), requester)
    is_search = target.startswith(("bilisearch", "ytsearch"))
    if is_search:
        hit = _SEARCH_CACHE.get(target)
        if hit and time.time() - hit[0] < params.SEARCH_CACHE_TTL:
            return [replace(t, id=uuid.uuid4().hex[:8], requester=requester) for t in hit[1]]
    tracks = _resolve_uncached(target, requester)
    if is_search and tracks:
        _SEARCH_CACHE[target] = (time.time(), tracks)
    return [replace(t, id=uuid.uuid4().hex[:8]) for t in tracks] if is_search else tracks


def _resolve_uncached(target: str, requester: str) -> list[Track]:
    """真正呼叫 yt-dlp 解析（不經快取） / The actual yt-dlp lookup (no cache)."""
    opts = _base_opts() | {"extract_flat": "in_playlist", "noplaylist": False, "playlistend": params.MAX_PLAYLIST}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(target, download=False)
    except yt_dlp.utils.DownloadError as exc:
        if "412" in str(exc):
            raise RuntimeError(
                "Bilibili 暫時限制了搜尋（HTTP 412）。請改貼影片網址／BV 號（直連影片通常不受影響），"
                "或稍後再試；登入自己的 Bilibili 帳號（看板上的「Bilibili 帳號」按鈕）也有助於降低被限流的機率。"
            ) from exc
        raise
    if info is None:
        return []
    entries = info.get("entries")
    if entries is None:  # 單一影片：資料已完整（含縮圖）/ a single video: the data is already complete (thumbnail included)
        return [_track_from_info(info, target, requester)]
    tracks = []
    for e in entries:
        if not e:
            continue
        url = e.get("webpage_url") or e.get("url")
        if not url:
            continue
        t = _track_from_info(e, url, requester)
        t.url = url
        tracks.append(t)
    return tracks


def enrich_track(t: Track) -> None:
    """補齊標題／縮圖／長度（搜尋與合集的 flat 結果通常沒有）

    Fill in title / thumbnail / duration (flat search and playlist results usually lack them).
    Failure is logged and tolerated: the track simply keeps what it has.
    """
    t.enriched = True
    if t.search:   # Spotify 的歌：資訊已經齊了，播放時才有對應影片 / a Spotify track already has its info; the matched video only exists at play time
        return
    try:
        with yt_dlp.YoutubeDL(_base_opts() | {"noplaylist": True}) as ydl:
            info = ydl.extract_info(t.url, download=False)
        if info.get("entries"):
            info = info["entries"][0]
        t.title = info.get("title") or t.title or t.url
        t.thumbnail = pick_thumb(info) or t.thumbnail
        t.duration = int(info["duration"]) if info.get("duration") else t.duration
        t.uploader = info.get("uploader") or t.uploader
    except Exception as exc:  # noqa: BLE001
        log.warning("補齊曲目資訊失敗 %s: %s", t.url, exc)
        t.title = t.title or t.url
