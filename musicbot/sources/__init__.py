"""來源解析 / Source resolving
把使用者輸入（網址／BV 號／Spotify／關鍵字）變成曲目，並取得最佳音訊串流（yt-dlp）
Turn what the user typed (URL / BV id / Spotify / keywords) into tracks, and fetch the best audio stream (via yt-dlp)

兩步刻意分開 / two steps on purpose:
  1. resolve_tracks  -> 輕量的 Track 清單，還沒有串流網址 / a light list of Tracks, no stream URL yet
  2. extract_stream_for -> 真正的音訊網址，播放前才取，因為會過期 / the real audio URL, fetched right before playing, because it expires

  tracks.py     資料結構 / data classes
  recognize.py  輸入辨識 / input recognition
  resolve.py    曲目解析與補資訊 / resolving and enrichment
  spotify.py    Spotify
  match.py      Spotify 對應歌曲 / song matching
  stream.py     取得串流 / the stream
"""
from .match import extract_stream_for, pick_match
from .recognize import _SPOTIFY_RE, normalize_query
from .resolve import clear_search_cache, enrich_track, pick_thumb, resolve_tracks
from .spotify import resolve_spotify
from .stream import extract_stream
from .tracks import BILI_HEADERS, Stream, Track, to_https

__all__ = [
    "BILI_HEADERS", "Stream", "Track", "to_https", "normalize_query", "resolve_tracks", "resolve_spotify", "enrich_track",
    "pick_thumb", "clear_search_cache", "pick_match", "extract_stream", "extract_stream_for", "_SPOTIFY_RE",
]
