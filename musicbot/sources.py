"""來源解析：把使用者輸入（網址／BV 號／關鍵字）轉成曲目，並取得最佳音訊串流（yt-dlp）

Source resolving: turn what the user typed (URL / BV id / keywords) into tracks, and fetch the best
audio stream for a track (via yt-dlp).

Two steps on purpose / 刻意分成兩步:
  1. ``resolve_tracks`` -> a light list of ``Track`` objects (title, thumbnail...). No stream URL yet.
  2. ``extract_stream``  -> the real audio URL, fetched right before playing, because those URLs expire.
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass, field, replace

import yt_dlp

from .paths import COOKIE_FILE

log = logging.getLogger("musicbot")

MAX_PLAYLIST = 50          # 合集／播放清單一次最多加入幾首 / max tracks taken from one playlist
SEARCH_CACHE_TTL = 600  # 秒；相同關鍵字短時間內不要重複打站方 API / seconds; don't hit the site's API again for the same keywords

# Bilibili 的 CDN 會檢查 Referer 與 User-Agent，沒帶會 403
# Bilibili's CDN checks Referer and User-Agent and answers 403 without them.
BILI_HEADERS = {
    "Referer": "https://www.bilibili.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
}


# ============================================================
# 資料結構 / Data classes
# ============================================================
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


# ============================================================
# 輸入辨識 / Input recognition
# ============================================================
_URL_RE = re.compile(r"https?://[^\s<>\"'「」『』【】（）]+", re.I)
_BV_RE = re.compile(r"(?<![0-9A-Za-z])(BV[0-9A-Za-z]{10})(?![0-9A-Za-z])")
_AV_RE = re.compile(r"(?<![0-9A-Za-z])av(\d{4,})(?![0-9A-Za-z])", re.I)
_PREFIX_RE = re.compile(r"^(yt|youtube|bili|bilibili)\s*[:：]\s*(.+)$", re.I | re.S)


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


# ============================================================
# 曲目解析 / Resolving tracks
# ============================================================
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
    is_search = target.startswith(("bilisearch", "ytsearch"))
    if is_search:
        hit = _SEARCH_CACHE.get(target)
        if hit and time.time() - hit[0] < SEARCH_CACHE_TTL:
            return [replace(t, id=uuid.uuid4().hex[:8], requester=requester) for t in hit[1]]
    tracks = _resolve_uncached(target, requester)
    if is_search and tracks:
        _SEARCH_CACHE[target] = (time.time(), tracks)
    return [replace(t, id=uuid.uuid4().hex[:8]) for t in tracks] if is_search else tracks


def _resolve_uncached(target: str, requester: str) -> list[Track]:
    """真正呼叫 yt-dlp 解析（不經快取） / The actual yt-dlp lookup (no cache)."""
    opts = _base_opts() | {"extract_flat": "in_playlist", "noplaylist": False, "playlistend": MAX_PLAYLIST}
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


# ============================================================
# 取得串流 / Fetching the stream
# ============================================================
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
        pick_thumb(info),
    )
