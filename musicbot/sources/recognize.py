"""輸入辨識：網址、BV 號、av 號、yt: 前綴、Spotify，其他當關鍵字

Input recognition: URL, BV id, av id, the yt: prefix, Spotify; anything else is keywords
"""
from __future__ import annotations

import re

_URL_RE = re.compile(r"https?://[^\s<>\"'「」『』【】（）]+", re.I)

_BV_RE = re.compile(r"(?<![0-9A-Za-z])(BV[0-9A-Za-z]{10})(?![0-9A-Za-z])")

_AV_RE = re.compile(r"(?<![0-9A-Za-z])av(\d{4,})(?![0-9A-Za-z])", re.I)

_PREFIX_RE = re.compile(r"^(yt|youtube|bili|bilibili)\s*[:：]\s*(.+)$", re.I | re.S)

_SPOTIFY_RE = re.compile(r"^https?://open\.spotify\.com/(?:intl-[a-z-]+/)?(?:embed/)?(track|album|playlist)/([0-9A-Za-z]{22})", re.I)

_SPOTIFY_URI_RE = re.compile(r"^spotify:(track|album|playlist):([0-9A-Za-z]{22})$", re.I)


def normalize_query(query: str) -> str:
    """自動辨識輸入類型，不需要使用者選來源

    - 內含網址（含 Bilibili App 分享出來的"標題 + 網址"整段文字）→ 直接用該網址
    - BV 號 / av 號 → Bilibili 影片
    - `yt:關鍵字` / `youtube:關鍵字` → YouTube 搜尋
    - 其他文字 → Bilibili 關鍵字搜尋

    Detect the input type automatically so users never have to pick a source.

    - contains a URL (including the "title + URL" blob the Bilibili app shares) -> use that URL
    - BV / av id -> that Bilibili video
    - ``yt:keywords`` / ``youtube:keywords`` -> YouTube search
    - anything else -> Bilibili keyword search
    """
    q = query.strip()
    m = _SPOTIFY_URI_RE.match(q)
    if m:
        return f"https://open.spotify.com/{m.group(1).lower()}/{m.group(2)}"
    m = _URL_RE.search(q)
    if m:
        return m.group(0).rstrip(".,;:!?。，、；：！？)]}>")
    m = _BV_RE.search(q)
    if m:
        return f"https://www.bilibili.com/video/{m.group(1)}"
    m = _AV_RE.search(q)
    if m:
        return f"https://www.bilibili.com/video/av{m.group(1)}"
    m = _PREFIX_RE.match(q)
    if m:
        engine = "ytsearch1" if m.group(1).lower() in ("yt", "youtube") else "bilisearch1"
        return f"{engine}:{m.group(2).strip()}"
    return f"bilisearch1:{q}"
