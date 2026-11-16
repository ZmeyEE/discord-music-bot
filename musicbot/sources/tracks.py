"""資料結構：一首歌（Track）、一個串流（Stream）、yt-dlp 的共同選項

Data classes: a song (Track), a stream (Stream), and the shared yt-dlp options
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from ..paths import COOKIE_FILE

# Bilibili 的 CDN 會檢查 Referer 與 User-Agent，沒帶會 403
# Bilibili's CDN checks Referer and User-Agent and answers 403 without them.
BILI_HEADERS = {
    "Referer": "https://www.bilibili.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
}


def to_https(url: str) -> str:
    """把 http:// 縮圖網址升級成 https://（頁面是 https 時避免混合內容被擋）

    Upgrade an ``http://`` URL to ``https://`` (avoids mixed-content blocking on https pages).
    """
    return "https://" + url[7:] if url.startswith("http://") else url


@dataclass
class Track:
    """待播清單裡的一首歌（只有中繼資料，沒有串流網址）

    One entry in a play queue: metadata only, no stream URL yet.
    """
    url: str
    title: str
    requester: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])   # 8 碼短 ID，前端用來辨識卡片 / short id the front-end uses to identify a card
    thumbnail: str = ""
    duration: int | None = None
    uploader: str = ""
    requester_avatar: str = ""      # 點歌者的 Discord 頭像網址（沒有 Discord 身分的訪客為空）/ requester's Discord avatar URL (empty for guests without a Discord identity)
    search: str = ""                # Spotify 的歌沒有音源，這裡放"歌名 歌手"，播放前才去 Bilibili／YouTube 找對應的 / Spotify has no audio, this holds "title artist" and the match is searched on Bilibili / YouTube right before playing
    matched: str = ""               # 找到的對應影片標題 / title of the video that was matched
    enriched: bool = False          # 補資訊試過了（成功或失敗都只試一次）/ enrichment was tried (once, success or not)

    def public(self) -> dict:
        """回傳可以安全送給網頁前端的欄位 / The fields that are safe to send to the web front-end."""
        return {
            "id": self.id,
            "title": self.title or self.url,
            "url": self.url,
            "thumbnail": self.thumbnail,
            "duration": self.duration,
            "uploader": self.uploader,
            "requester": self.requester,
            "requester_avatar": self.requester_avatar,
        }


@dataclass
class Stream:
    """真正可播放的音訊串流（有時效，播放前才取）

    A playable audio stream. It expires, so it is fetched just before playback.
    """
    url: str
    headers: dict
    title: str
    duration: int | None
    quality: str
    thumbnail: str


def _base_opts() -> dict:
    """yt-dlp 的共同選項；有登入 cookie 就帶上 / Options shared by every yt-dlp call; the login cookie is attached when present."""
    opts: dict = {"quiet": True, "no_warnings": True, "skip_download": True}
    if COOKIE_FILE.exists():
        opts["cookiefile"] = str(COOKIE_FILE)
    return opts
