"""取得串流：最高品質音訊的網址（有時效，播放前才取）

Fetching the stream: the best-quality audio URL (it expires, so it is fetched right before playback)
"""
from __future__ import annotations

import yt_dlp

from .resolve import pick_thumb
from .tracks import BILI_HEADERS, Stream, _base_opts


def extract_stream(url: str) -> Stream:
    """取得該曲目最高品質的音訊串流

    Get the best-quality audio stream for a track.
    """
    # 音軌優先順序：無損 FLAC（Bilibili Hi-Res，需大會員 cookie）> 一般最佳音軌（略過杜比 E-AC-3：多聲道，降混成立體聲反而變差）> 任何可用格式
    # Format preference: lossless FLAC (Bilibili Hi-Res, needs a premium cookie) > best regular audio
    # (skipping Dolby E-AC-3: multichannel, and the stereo down-mix sounds worse) > anything playable.
    opts = _base_opts() | {
        "format": "bestaudio[acodec=flac]/bestaudio[acodec!*=ec-3]/bestaudio/best",
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if info.get("entries"):
        info = info["entries"][0]
    abr = info.get("abr")
    quality = f"{info.get('acodec', '?')} {abr:.0f}kbps" if abr else str(info.get("acodec", "?"))
    headers = dict(info.get("http_headers") or {})
    if "bilibili" in (info.get("webpage_url") or url) or "bilivideo" in info["url"]:
        headers.update(BILI_HEADERS)
    return Stream(
        info["url"], headers, info.get("title") or url, info.get("duration"), quality,
        pick_thumb(info), codec=str(info.get("acodec") or ""), abr=float(abr or 0),
    )
