"""對應歌曲：Spotify 的歌去 Bilibili（不行換 YouTube）找最像的

Song matching: find the closest hit on Bilibili (YouTube as a fallback) for a Spotify song
"""
from __future__ import annotations

import re

import yt_dlp

from .. import params
from .stream import extract_stream
from .tracks import Stream, Track, _base_opts

_BAD_WORDS = re.compile(r"伴奏|纯音乐|純音樂|instrumental|karaoke|翻唱|cover|remix|reverb|nightcore|8d|sped up|slowed", re.I)


def pick_match(cands: list[dict], want: float | None, title: str = "") -> dict | None:
    """從搜尋結果挑最像的：長度差在幾秒內、不是伴奏／翻唱／混音（除非原曲名就有），都沒有就取第一個

    Pick the best search hit: duration within a few seconds, not an instrumental / cover / remix (unless the
    Spotify title says so itself); falls back to the first hit.
    """
    cands = [c for c in cands if c and (c.get("webpage_url") or c.get("url"))]
    if not cands:
        return None
    clean = [c for c in cands if not _BAD_WORDS.search(c.get("title") or "") or _BAD_WORDS.search(title)]
    if want:
        tol = max(params.MATCH_TOLERANCE_SECONDS, want * params.MATCH_TOLERANCE_RATIO)
        close = [c for c in clean if c.get("duration") and abs(c["duration"] - want) <= tol]
        if close:
            return close[0]
    return (clean or cands)[0]


def extract_stream_for(t: Track) -> Stream:
    """取得一首歌的串流；Spotify 的歌先去 Bilibili 找對應的（找不到再試 YouTube）

    Get a track's stream. A Spotify track is first matched on Bilibili (YouTube as a fallback).
    """
    if not t.search:
        return extract_stream(t.url)
    last: Exception | None = None
    for engine in (f"bilisearch{params.MATCH_CANDIDATES}", f"ytsearch{params.MATCH_CANDIDATES}"):
        try:
            with yt_dlp.YoutubeDL(_base_opts() | {"extract_flat": "in_playlist", "noplaylist": False}) as ydl:
                info = ydl.extract_info(f"{engine}:{t.search}", download=False)
            hit = pick_match(list((info or {}).get("entries") or []), t.duration, t.title)
        except Exception as exc:  # noqa: BLE001 - 這個站搜不到或被限流，換下一個 / this site failed or rate-limited us: try the next
            last, hit = exc, None
        if hit:
            stream = extract_stream(hit.get("webpage_url") or hit.get("url"))
            t.matched = hit.get("title") or stream.title   # Bilibili 的搜尋結果常常沒有標題，用串流的 / Bilibili search hits often lack a title, use the stream's
            return stream
    raise RuntimeError(f"找不到對應的歌（{t.search}）" + (f"：{str(last)[:80]}" if last else ""))
