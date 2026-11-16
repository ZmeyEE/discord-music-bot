"""對應歌曲：Spotify 的歌沒有音源，去 Bilibili 和 YouTube 找"同一首、音質最好"的影片

怎麼挑：
  1. 搜尋結果先過濾：標題有循環版、合集、倍速、翻唱、伴奏這類字的不要（除非原曲名自己就有）
  2. 真的去取串流，看實際長度：和原曲差太多的不要（搜尋結果常常沒帶長度，42 分鐘的循環版就是這樣混進來的）
  3. 剩下的比音質：無損 > 位元率高的；夠好就不再找下一個站
  4. 找到之後記在曲目上，下次（循環、重播）直接用同一支，不用再搜一次

Song matching: a Spotify song has no audio, so find "the same song at the best quality" on Bilibili and YouTube.

How a video is picked:
  1. Filter the search hits: drop titles that say loop version, compilation, sped up, cover, instrumental... (unless the
     song's own title says so).
  2. Really fetch the stream and look at the true length: drop the ones far from the song's length (search hits often carry
     no length, which is how a 42-minute loop version slipped in).
  3. Compare the audio quality of what is left: lossless > higher bitrate. Once it is good enough, the next site is skipped.
  4. The pick is remembered on the track, so a loop or replay uses the same video without searching again.
"""
from __future__ import annotations

import logging
import re

import yt_dlp

from .. import params
from .stream import extract_stream
from .tracks import Stream, Track, _base_opts

log = logging.getLogger("musicbot")

ENGINES = ("bilisearch", "ytsearch")   # 先 Bilibili 再 YouTube / Bilibili first, then YouTube


def skip_words() -> re.Pattern:
    """不要的標題用字（params.MATCH_SKIP_WORDS）/ The unwanted title words (params.MATCH_SKIP_WORDS)."""
    return re.compile(params.MATCH_SKIP_WORDS, re.I)


def tolerance(want: float) -> float:
    """長度差多少以內算同一首 / How far a length may be off and still count as the same song."""
    return max(params.MATCH_TOLERANCE_SECONDS, want * params.MATCH_TOLERANCE_RATIO)


def rank(cands: list[dict], want: float | None, title: str = "") -> list[dict]:
    """把搜尋結果排成"值得試"的順序：去掉不要的字、去掉長度明顯不對的，長度對的排前面，不知道長度的排後面

    Order search hits by how worth trying they are: unwanted words out, clearly wrong lengths out, right lengths first and
    unknown lengths after them.
    """
    bad = skip_words()
    cands = [c for c in cands if c and (c.get("webpage_url") or c.get("url"))]
    clean = [c for c in cands if not bad.search(c.get("title") or "") or bad.search(title)]
    if not want:
        return clean
    close = [c for c in clean if c.get("duration") and abs(c["duration"] - want) <= tolerance(want)]
    unknown = [c for c in clean if not c.get("duration")]
    return close + unknown


def pick_match(cands: list[dict], want: float | None, title: str = "") -> dict | None:
    """最值得試的那一個；沒有就 None / The hit most worth trying, or None."""
    ranked = rank(cands, want, title)
    return ranked[0] if ranked else None


def quality_score(stream: Stream) -> float:
    """音質分數，用來比較兩條串流：無損最高；其餘看位元率，Opus 同位元率比 AAC 好所以加權

    A quality score to compare two streams: lossless wins; otherwise the bitrate, with Opus weighted up because it sounds
    better than AAC at the same bitrate.
    """
    codec = stream.codec.lower()
    if codec.startswith(("flac", "alac", "pcm")):
        return params.MATCH_LOSSLESS_SCORE
    return stream.abr * (params.MATCH_OPUS_WEIGHT if codec.startswith("opus") else 1.0)


def length_ok(stream: Stream, want: float | None, title: str) -> bool:
    """實際長度對得上嗎，標題也再檢查一次（搜尋結果的標題常常是空的）

    Does the true length fit? The title is checked once more too (search hits often come without one).
    """
    bad = skip_words()
    if bad.search(stream.title or "") and not bad.search(title):
        return False
    return not want or not stream.duration or abs(stream.duration - want) <= tolerance(want)


def search(engine: str, query: str) -> list[dict]:
    """在一個站搜尋，回傳搜尋結果（不取串流）/ Search one site and return the hits (no stream is fetched)."""
    with yt_dlp.YoutubeDL(_base_opts() | {"extract_flat": "in_playlist", "noplaylist": False}) as ydl:
        info = ydl.extract_info(f"{engine}{params.MATCH_CANDIDATES}:{query}", download=False)
    return list((info or {}).get("entries") or [])


def find_best(t: Track) -> tuple[Stream, str] | None:
    """照檔頭的四個步驟找最好的對應影片，回傳 (串流, 影片網址)；找不到回傳 None

    Find the best matching video by the four steps at the top of this file: ``(stream, video URL)``, or None.
    """
    best: tuple[Stream, str] | None = None
    for engine in ENGINES:
        try:
            hits = rank(search(engine, t.search), t.duration, t.title)
        except Exception as exc:  # noqa: BLE001 - 這個站搜不到或被限流，換下一個 / this site failed or rate-limited us: try the next
            log.info("對應歌曲：%s 搜尋失敗（%s），換下一個站", engine, str(exc)[:80])
            continue
        for hit in hits[: params.MATCH_PROBE]:
            url = hit.get("webpage_url") or hit.get("url")
            try:
                stream = extract_stream(url)
            except Exception:  # noqa: BLE001 - 這支取不到就試下一支 / this one can't be fetched: try the next
                continue
            if not length_ok(stream, t.duration, t.title):
                continue
            if best is None or quality_score(stream) > quality_score(best[0]):
                best = (stream, url)
            if quality_score(best[0]) >= params.MATCH_GOOD_SCORE:
                return best
    return best


def extract_stream_for(t: Track) -> Stream:
    """取得一首歌的串流；Spotify 的歌先找對應影片（找過就沿用）

    Get a track's stream. A Spotify track is matched to a video first (a previous match is reused).
    """
    if not t.search:
        return extract_stream(t.url)
    if t.matched_url:
        try:
            return extract_stream(t.matched_url)
        except Exception:  # noqa: BLE001 - 那支影片不見了，重新找 / that video is gone: match again
            t.matched_url = ""
    found = find_best(t)
    if found is None:
        raise RuntimeError(f"找不到對應的歌（{t.search}）")
    stream, t.matched_url = found
    t.matched = stream.title
    log.info("對應歌曲：%s -> %s | %s", t.search, stream.title, stream.quality)
    return stream
