"""來源解析：把使用者輸入（網址／BV 號／關鍵字）轉成曲目，並取得最佳音訊串流（yt-dlp）

Source resolving: turn what the user typed (URL / BV id / keywords) into tracks, and fetch the best
audio stream for a track (via yt-dlp).

Two steps on purpose / 刻意分成兩步:
  1. ``resolve_tracks`` -> a light list of ``Track`` objects (title, thumbnail...). No stream URL yet.
  2. ``extract_stream``  -> the real audio URL, fetched right before playing, because those URLs expire.
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.request
import uuid
from dataclasses import dataclass, field, replace

import yt_dlp

from .paths import COOKIE_FILE

log = logging.getLogger("musicbot")

MAX_PLAYLIST = 5000        # 合集／播放清單一次最多加入幾首 / max tracks taken from one playlist
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


# ============================================================
# 輸入辨識 / Input recognition
# ============================================================
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
    spotify = _SPOTIFY_RE.match(target)
    if spotify:
        return resolve_spotify(spotify.group(1).lower(), spotify.group(2), requester)
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


# ============================================================
# Spotify / Spotify links
# ============================================================
# Spotify 的音訊有 DRM，沒辦法直接播
# 這裡只讀公開嵌入頁（不用金鑰、不用登入）拿歌名和歌手，播放前再去 Bilibili／YouTube 找對應的歌
# Spotify audio is DRM protected, so it can't be played directly.
# We only read the public embed page (no key, no login) for title and artists, then search the match on Bilibili / YouTube right before playing.
_SPOTIFY_UA = BILI_HEADERS["User-Agent"]
_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
_BAD_WORDS = re.compile(r"伴奏|纯音乐|純音樂|instrumental|karaoke|翻唱|cover|remix|reverb|nightcore|8d|sped up|slowed", re.I)


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
    return tracks[:MAX_PLAYLIST]


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
        tol = max(6.0, want * 0.05)
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
    for engine in ("bilisearch5", "ytsearch5"):
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
