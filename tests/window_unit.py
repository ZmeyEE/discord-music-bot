"""待播清單視窗的單元測試（不需要 Discord、不連網）：只給前面一段、清單沒變就不重送
Unit tests of the queue window (no Discord, no network): only the first part is sent, and an unchanged list is not sent again

用 tests/run_all.py 執行；走真的看板和 WebSocket 的那一半在 window_test.py
Run it with tests/run_all.py; the half that goes through the real dashboard and WebSocket is window_test.py
"""
import os
import sys
import time
from collections import deque
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 專案根目錄 / project root
sys.path.insert(0, ROOT)
from musicbot import params
from musicbot.dashboard.queuewindow import QueueView
from musicbot.player import PlayerBot
from musicbot.sources import Track

res = []
def check(n, ok, d=""): res.append(bool(ok)); print(("PASS" if ok else "FAIL"), n, str(d)[:190], flush=True)

PAGE, VIEW = params.QUEUE_PAGE, params.QUEUE_VIEW
check("P1 一頁 100、一個瀏覽器最多 1000", (PAGE, VIEW) == (100, 5000), (PAGE, VIEW))

# ============ 視窗大小 ============
v = QueueView()
check("A1 一開始要一頁，而且還不省略清單（舊版網頁每次都要拿到）", v.limit == PAGE and v.delta is False)
v.ask(None)
check("A2 送一次 queue_window（沒帶數字）= 懂省略，大小不變", v.delta is True and v.limit == PAGE)
v.ask(300); a3 = v.limit
v.ask(10); a4 = v.limit
v.ask(10 ** 9); a5 = v.limit
check("A3 數字限制在一頁到上限之間", (a3, a4, a5) == (300, PAGE, VIEW), (a3, a4, a5))
v.ask("abc"); v.ask(True); v.ask({"x": 1})
check("A4 不是數字的維持原大小", v.limit == VIEW, v.limit)

# ============ 清單沒變就不重送 ============
def snap(selected="p1", sig=111): return {"selected": selected, "queue": [1, 2, 3], "queue_total": 3, "queue_sig": sig}
old = QueueView()                      # 沒送過 queue_window 的舊版網頁 / an old page that never sent queue_window
first, second = old.trim(snap()), old.trim(snap())
check("T1 舊版網頁：每次都帶清單，指紋不外流", "queue" in first and "queue" in second and "queue_sig" not in first)
new = QueueView(); new.ask(None)
t1, t2 = new.trim(snap()), new.trim(snap())
check("T2 新版網頁：第一次帶清單，沒變就不帶", "queue" in t1 and "queue" not in t2 and t2["queue_total"] == 3, list(t2))
check("T3 清單內容變了（指紋不同）就再帶一次", "queue" in new.trim(snap(sig=222)))
check("T4 換到別的播放器也要再帶一次", "queue" in new.trim(snap(selected="p2", sig=222)) and "queue" not in new.trim(snap(selected="p2", sig=222)))
pending = {"guild": {"id": "1"}, "me": {"pending": True}}
check("T5 還沒驗證的人拿到的快照（沒有清單）原樣不動", new.trim(dict(pending)) == pending)
new.ask(300)
check("T6 視窗變大後下一份會帶清單（指紋跟著變）", "queue" in new.trim(snap(sig=333)))


# ============ 播放器快照 ============
def make(n):
    w = PlayerBot.__new__(PlayerBot)
    w.states = {}
    st = w.state(1)
    st.queue = deque(Track(url=f"u{i}", title=f"t{i}", requester="me", thumbnail="x") for i in range(n))
    return w, st

g = SimpleNamespace(id=1, voice_client=None)
w, st = make(1500)
d = w.player_state(g, PAGE)
check("S1 5000 首也只給一頁，總數另外給", len(d["queue"]) == PAGE and d["queue_total"] == 1500, (len(d["queue"]), d["queue_total"]))
from unittest import mock
with mock.patch.object(params, "QUEUE_VIEW", 1000):
    check("S2 沒說要幾首 = 給到上限；要太多也只給上限（這裡把上限調成 1000 來測）", len(w.player_state(g)["queue"]) == 1000 and len(w.player_state(g, 99999)["queue"]) == 1000)
check("S2b 上限 5000 大於清單時，就是整份清單", len(w.player_state(g)["queue"]) == 1500 and len(w.player_state(g, 99999)["queue"]) == 1500)
sig = d["queue_sig"]
check("S3 內容沒變，指紋不變", w.player_state(g, PAGE)["queue_sig"] == sig)
st.queue[500].title = "視窗外面的歌改名"
check("S4 視窗外面的歌變了，指紋不變（不用重送）", w.player_state(g, PAGE)["queue_sig"] == sig)
st.queue[5].thumbnail = "補到縮圖了"
sig2 = w.player_state(g, PAGE)["queue_sig"]
check("S5 視窗裡的歌變了，指紋跟著變", sig2 != sig)
st.queue.popleft()
check("S6 播掉一首（整個往前移），指紋跟著變", w.player_state(g, PAGE)["queue_sig"] != sig2)
st.queue.rotate(-1); st.queue.rotate(1)
t0 = time.perf_counter()
for _ in range(50):
    w.player_state(g, PAGE)
ms = (time.perf_counter() - t0) * 1000 / 50
check("S7 取一頁的快照很快（< 2 毫秒）", ms < 2, round(ms, 3))

print(f"{sum(res)}/{len(res)} 通過", flush=True)
sys.exit(0 if all(res) else 1)
