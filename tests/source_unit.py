"""來源解析的單元測試（不需要 Discord、不連網）：5000 首上限、Spotify 連結、對應歌曲、待播清單上限
Unit tests for source resolving (no Discord, no network): the 5000 limit, Spotify links, song matching, the queue cap

用 tests/run_all.py 執行 / run it with tests/run_all.py
"""
import asyncio
import urllib.request
import json
import os
import sys
from collections import deque
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 專案根目錄 / project root
sys.path.insert(0, ROOT)
from musicbot import player as P
from musicbot.player import enqueue as E
from musicbot import params
from musicbot import sources as S
from musicbot.player import PlayerBot

res = []
def check(n, ok, d=""): res.append(bool(ok)); print(("PASS" if ok else "FAIL"), n, str(d)[:190], flush=True)

# ============ 輸入辨識 ============
check("N1 合集上限 5000", params.MAX_PLAYLIST == 5000 and params.MAX_QUEUE == 5000, (params.MAX_PLAYLIST, params.MAX_QUEUE))
TRK = "4cOdK2wGLETKBW3PvgPWqT"
check("N2 Spotify 網址（含 ?si= 追蹤參數）", S.normalize_query(f"https://open.spotify.com/track/{TRK}?si=abc").startswith("https://open.spotify.com/track/"))
check("N3 spotify: 這種 URI 也認得", S.normalize_query(f"spotify:track:{TRK}") == f"https://open.spotify.com/track/{TRK}")
check("N4 intl-ja 與 embed 路徑也認得", bool(S._SPOTIFY_RE.match(f"https://open.spotify.com/intl-ja/playlist/{TRK}")) and bool(S._SPOTIFY_RE.match(f"https://open.spotify.com/embed/album/{TRK}")))
check("N5 一般關鍵字照舊走 Bilibili 搜尋", S.normalize_query("周杰倫 晴天") == "bilisearch1:周杰倫 晴天")

# ============ Spotify 嵌入頁（用錄下來的格式，不連網）============
def page(entity):
    data = {"props": {"pageProps": {"state": {"data": {"entity": entity}}}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></html>'

class Resp:
    def __init__(self, html): self.html = html
    def read(self): return self.html.encode()
    def __enter__(self): return self
    def __exit__(self, *a): return False

def with_page(entity, fn):
    with mock.patch.object(urllib.request, "urlopen", lambda req, timeout=0: Resp(page(entity))):
        return fn()

img = {"image": [{"url": "http://x/small", "maxWidth": 64}, {"url": "http://x/mid", "maxWidth": 300}, {"url": "http://x/big", "maxWidth": 640}]}
single = {"name": "Song", "artists": [{"name": "A"}, {"name": "B"}], "duration": 200000, "visualIdentity": img}
t = with_page(single, lambda: S.resolve_spotify("track", TRK, "me"))[0]
check("S1 單曲：標題、歌手、秒數、搜尋字串", t.title == "Song - A, B" and t.duration == 200 and t.search == "Song A" and t.uploader == "A, B", (t.title, t.search))
check("S2 封面挑夠用的最小一張並升成 https", t.thumbnail == "https://x/mid", t.thumbnail)

tl = [{"uri": f"spotify:track:{i:022d}", "title": f"T{i}", "subtitle": "X, Y", "duration": 180000, "isPlayable": True} for i in range(100)]
tl.append({"uri": "spotify:track:" + "9" * 22, "title": "Gone", "subtitle": "Z", "isPlayable": False})
tl.append({"uri": "spotify:episode:abc", "title": "Podcast", "subtitle": "P"})
album = with_page({"name": "Al", "trackList": tl, "visualIdentity": img}, lambda: S.resolve_spotify("album", TRK, "me"))
check("S3 專輯：略過不能播的和非歌曲項目", len(album) == 100 and album[0].url.endswith("0" * 22) and album[0].thumbnail, len(album))
plist = with_page({"name": "Pl", "trackList": tl[:3], "visualIdentity": img}, lambda: S.resolve_spotify("playlist", TRK, "me"))
check("S4 播放清單的每首不套用清單封面", all(not x.thumbnail for x in plist) and plist[1].search == "T1 X")
try:
    with_page({"name": "Empty", "trackList": []}, lambda: S.resolve_spotify("playlist", TRK, "me"))
    check("S5 空清單要給明確錯誤", False)
except RuntimeError as exc:
    check("S5 空清單要給明確錯誤", "讀不到任何歌" in str(exc), exc)
with mock.patch.object(urllib.request, "urlopen", lambda req, timeout=0: Resp("<html>nothing</html>")):
    try:
        S.resolve_spotify("track", TRK, "me"); check("S6 頁面格式變了要給明確錯誤", False)
    except RuntimeError as exc:
        check("S6 頁面格式變了要給明確錯誤", "格式變了" in str(exc), exc)

# ============ 對應歌曲 ============
def c(title, dur, url="https://v/x"): return {"title": title, "duration": dur, "url": url + title}
check("M1 長度最接近的優先（差 6 秒內）", S.pick_match([c("a", 263), c("b", 204), c("c", 201)], 200)["title"] == "b")
check("M2 略過伴奏／翻唱／混音", S.pick_match([c("Song (Cover)", 200), c("Song 伴奏", 200), c("Song official", 201)], 200, "Song")["title"] == "Song official")
check("M3 原曲名就有 remix 時不略過", S.pick_match([c("Song (Remix)", 200)], 200, "Song (Remix)")["title"] == "Song (Remix)")
check("M4 長度都對不上就取第一個", S.pick_match([c("x", 100), c("y", 500)], 200)["title"] == "x")
check("M5 沒有結果回 None", S.pick_match([], 200) is None and S.pick_match([{"title": "no url"}], 200) is None)
check("M6 沒有長度資訊也能挑", S.pick_match([c("x", None)], None)["title"] == "x")

# ============ 待播清單上限 ============
def make():
    w = PlayerBot.__new__(PlayerBot)
    w.hub, w.index, w.is_primary = SimpleNamespace(notify=lambda g: None), 0, True
    w.states, w._recover_tasks, w._enrich_sem, w._watch_task, w._gateway_drop = {}, {}, None, None, float("-inf")
    w._connection = SimpleNamespace(user=SimpleNamespace(name="t", id=5))
    async def ensure_voice(g, ch=None): return SimpleNamespace(is_playing=lambda: False, is_paused=lambda: False)
    async def ensure_playing(g): pass
    w.ensure_voice, w.ensure_playing = ensure_voice, ensure_playing
    return w

async def queue_cap():
    g = SimpleNamespace(id=1)
    def tracks(n): return [S.Track(url=f"u{i}", title=f"t{i}", requester="me", thumbnail="x") for i in range(n)]
    with mock.patch.object(E, "resolve_tracks", lambda q, r: tracks(60)), mock.patch.object(params, "MAX_QUEUE", 100):
        w = make()
        added, note = await w._enqueue(g, "q", "me", None, "end")
        check("Q1 沒滿：全部加入、沒有提示", len(added) == 60 and note is None and len(w.state(1).queue) == 60)
        added, note = await w._enqueue(g, "q", "me", None, "end")
        check("Q2 只剩 40 個位置：只加 40 首並提示", len(added) == 40 and note and "40" in note and len(w.state(1).queue) == 100, note)
        added, note = await w._enqueue(g, "q", "me", None, "end")
        check("Q3 滿了：一首都不加、有提示", added == [] and note and "滿了" in note and len(w.state(1).queue) == 100, note)
    with mock.patch.object(E, "resolve_tracks", lambda q, r: tracks(5000)):
        w = make()
        added, note = await w._enqueue(g, "q", "me", None, "end")
        check("Q4 一次加 5000 首", len(added) == 5000 and note is None and len(w.state(1).queue) == 5000)
    # 補縮圖：只先補前 50 首、Spotify 的歌不補
    started = []
    async def fake_many(self, gid, ts): started.append(len(ts))
    sp = [S.Track(url=f"s{i}", title="s", requester="me", search="s") for i in range(5)]
    plain = [S.Track(url=f"p{i}", title="", requester="me") for i in range(300)]
    with mock.patch.object(E, "resolve_tracks", lambda q, r: sp + plain), mock.patch.object(PlayerBot, "enrich_many", fake_many):
        w = make()
        await w._enqueue(g, "q", "me", None, "end")
        await asyncio.sleep(0)
    check("Q5 一次最多先補 50 首縮圖，Spotify 的不補", started == [50], started)
    w = make(); st = w.state(1)
    st.queue = deque(S.Track(url=f"p{i}", title="", requester="me") for i in range(30))
    st.queue[0].enriched = True
    with mock.patch.object(PlayerBot, "enrich_many", fake_many):
        started.clear(); w._enrich_ahead(1); await asyncio.sleep(0)
    check("Q6 開始播時往後補 10 首，試過的不再補", started == [9], started)
    w = make(); st = w.state(1)
    st.queue = deque(S.Track(url=f"p{i}", title="t", requester="me") for i in range(1500))
    d = w.player_state(SimpleNamespace(id=1, voice_client=None))
    check("Q7 看板最多收到前 1000 首，總數另外給", len(d["queue"]) == params.QUEUE_VIEW == 1000 and d["queue_total"] == 1500, (len(d["queue"]), d["queue_total"]))

asyncio.run(queue_cap())
print(f"{sum(res)}/{len(res)} 通過", flush=True)
sys.exit(0 if all(res) else 1)
