"""我的歌單的單元測試（資料夾樹與存檔）：不需要網路與 Discord
Unit tests of the library (folder tree and persistence): no network, no Discord

用 tests/run_all.py 執行 / run it with tests/run_all.py
"""
import os
import sys
import tempfile
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 專案根目錄 / project root
sys.path.insert(0, ROOT)
from musicbot import params
from musicbot.library import Library, LibraryError, tree as T

res = []
def check(n, ok, d=""): res.append(bool(ok)); print(("PASS" if ok else "FAIL"), n, str(d)[:190], flush=True)
def raises(fn, *a):
    try: fn(*a)
    except LibraryError as e: return str(e)
    return None
def song(i, **kw): return {"url": f"https://www.bilibili.com/video/BV{i:010d}", "title": f"歌{i}", "duration": 200 + i, "thumbnail": f"https://i/{i}.jpg", "uploader": "上傳者", **kw}

# ============ 歌與名稱 ============
check("S1 歌要有連結，沒有的不存", T.clean_song({"title": "x"}) is None and T.clean_song({"url": " "}) is None)
s = T.clean_song({"url": "https://x/" + "a" * 900, "title": "t" * 500, "duration": -5, "junk": 1})
check("S2 欄位被整理並限制長度，亂來的欄位被丟掉", len(s["url"]) == 500 and len(s["title"]) == 200 and s["duration"] is None and "junk" not in s, s)
check("S3 名稱：去掉多餘空白、限制長度、空的用預設", T.clean_name("  a \n b  ", "x") == "a b" and len(T.clean_name("字" * 99, "x")) == params.LIB_NAME_MAX and T.clean_name("   ", "預設") == "預設")

# ============ 建立 ============
root = T.new_root()
f1 = T.add_folder(root, "root", "華語")
p1 = T.add_playlist(root, f1["id"], "抒情", [song(1), song(2), {"title": "沒連結"}])
p2 = T.add_playlist(root, "root", "跑步用", [song(3)])
check("T1 歌單裡只放有連結的歌", [x["title"] for x in p1["songs"]] == ["歌1", "歌2"], p1["songs"])
check("T2 數量統計", T.count_songs(root) == 3 and T.count_nodes(root) == 3)
check("T3 資料夾底下所有的歌依順序", [x["title"] for x in T.songs_of(f1)] == ["歌1", "歌2"] and [x["title"] for x in T.songs_of(root)] == ["歌1", "歌2", "歌3"])
check("T4 找不到的資料夾有明確錯誤", raises(T.add_folder, root, "nope", "x") == "找不到這個資料夾" and raises(T.add_songs, root, f1["id"], [song(9)]) == "找不到這張歌單")

# ============ 改名／刪除 ============
T.rename(root, p2["id"], "  晨跑  ")
check("R1 改名", p2["name"] == "晨跑" and raises(T.rename, root, "root", "x") is not None)
f2 = T.add_folder(root, "root", "日語")
inner = T.add_folder(root, f2["id"], "動漫")
T.add_playlist(root, inner["id"], "OP", [song(4)])
check("R2 刪除資料夾連同裡面的東西", T.delete(root, [f2["id"]]) == 1 and T.find(root, inner["id"]) is None and T.count_songs(root) == 3)
check("R3 刪除時選了上層和下層，只算一次且不出錯", T.delete(root, [f1["id"], p1["id"]]) == 1 and T.find(root, p1["id"]) is None)
check("R4 根不能刪", T.delete(root, ["root"]) == 0)
f1 = T.add_folder(root, "root", "華語"); p1 = T.add_playlist(root, f1["id"], "抒情", [song(1), song(2), song(5)])
check("R5 依位置移除歌", T.remove_songs(root, p1["id"], [0, 2, 99, -1]) == 2 and [x["title"] for x in p1["songs"]] == ["歌2"])

# ============ 搬移與多選成資料夾 ============
a = T.add_folder(root, "root", "A"); b = T.add_folder(root, "root", "B")
pa = T.add_playlist(root, "root", "甲", [song(6)]); pb = T.add_playlist(root, "root", "乙", [song(7)])
check("M1 搬進資料夾", T.move(root, [pa["id"], pb["id"]], a["id"]) == 2 and [c["name"] for c in a["children"]] == ["甲", "乙"])
check("M2 不能搬進自己或自己底下", raises(T.move, root, [a["id"]], a["id"]) is not None and raises(T.move, root, [a["id"]], T.add_folder(root, a["id"], "A1")["id"]) is not None)
g = T.group(root, [b["id"], a["id"]], "合輯")
check("M3 多選的項目一起進新資料夾，建在第一個被選項目的位置", [c["name"] for c in g["children"]] == ["B", "A"] and root["children"][[c["name"] for c in root["children"]].index("合輯")]["id"] == g["id"], [c["name"] for c in root["children"]])
check("M4 沒選東西不能建資料夾", raises(T.group, root, [], "x") == "請先選要放進資料夾的項目")

# ============ 層數與上限 ============
deep = T.new_root(); cur = "root"
for i in range(params.LIB_MAX_DEPTH): cur = T.add_folder(deep, cur, f"L{i}")["id"]
check("D1 巢狀超過上限就拒絕", raises(T.add_folder, deep, cur, "太深") is not None and T.depth_of(deep, cur) == params.LIB_MAX_DEPTH)
side = T.add_folder(deep, "root", "旁邊")
sub = T.add_folder(deep, side["id"], "子")
check("D2 搬資料夾時算上它自己底下的層數", raises(T.move, deep, [side["id"]], cur) is not None)
with mock.patch.object(params, "LIB_MAX_SONGS", 3):
    r = T.new_root(); pl = T.add_playlist(r, "root", "x", [song(i) for i in range(10)])
    check("D3 歌太多時只放得下上限，滿了再放會有錯誤", len(pl["songs"]) == 3 and raises(T.add_songs, r, pl["id"], [song(1)]) is not None)
with mock.patch.object(params, "LIB_MAX_NODES", 2):
    r = T.new_root(); T.add_folder(r, "root", "1"); T.add_folder(r, "root", "2")
    check("D4 資料夾和歌單太多會被拒絕", raises(T.add_folder, r, "root", "3") is not None and raises(T.add_playlist, r, "root", "p", []) is not None)

# ============ 跨資料夾循環要的"下一個資料夾" ============
r = T.new_root(); fa, fb, fc = (T.add_folder(r, "root", n) for n in "ABC"); T.add_playlist(r, "root", "p", [])
check("N1 同一層的下一個資料夾，到底繞回第一個，歌單不算", T.next_sibling_folder(r, fa["id"])["id"] == fb["id"] and T.next_sibling_folder(r, fc["id"])["id"] == fa["id"])
check("N2 只有自己時回傳自己；找不到回 None", T.next_sibling_folder(T.new_root(), "zz") is None and T.next_sibling_folder(*(lambda x: (x, T.add_folder(x, "root", "only")["id"]))(T.new_root()))["name"] == "only")

# ============ 給網頁的摘要 ============
o = T.outline(root)
lists = [x for x in o["children"] if x["type"] == "playlist"]
check("O1 摘要有名稱、數量、封面，沒有每首歌", o["type"] == "folder" and lists and all("songs" not in c and "count" in c and "covers" in c for c in lists), lists[:1])
check("O2 封面最多 4 張、略過沒有縮圖的", len(T.outline(T.add_playlist(T.new_root(), "root", "x", [song(i, thumbnail="" if i == 0 else f"u{i}") for i in range(9)]))["covers"]) == 4)

# ============ 歌單裡的歌變回曲目 ============
from musicbot.player import PlayerBot
tr = PlayerBot.tracks_from_songs([song(1), song(2, thumbnail=""), {"url": "https://open.spotify.com/track/x", "title": "S", "search": "S 歌手"}], "小明", "http://a/v.png")
check("B1 歌變回曲目：點歌者與頭像是播放的人，已有縮圖的不再補資料", [t.requester for t in tr] == ["小明"] * 3 and tr[0].requester_avatar == "http://a/v.png" and tr[0].enriched and not tr[1].enriched, [(t.requester, t.enriched) for t in tr])
check("B2 Spotify 的歌保留找對應影片的關鍵字", tr[2].search == "S 歌手" and tr[2].url.startswith("https://open.spotify.com"))
check("B3 每首曲目都有自己的 id", len({t.id for t in tr}) == 3)

# ============ 存檔 ============
with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "library.json")
    lib = Library(path)
    check("P1 沒有檔案就是空的", lib.users == {} and not os.path.exists(path))
    root = lib.root("123"); T.add_playlist(root, "root", "存起來", [song(1), song(2)]); lib.save()
    lib2 = Library(path)
    check("P2 存檔後重新讀回來一樣", [x["title"] for x in T.songs_of(lib2.root("123"))] == ["歌1", "歌2"] and not os.path.exists(path + ".tmp"))
    check("P3 每個人各自一棵", T.count_songs(lib2.root("456")) == 0 and T.count_songs(lib2.root("123")) == 2)
    with open(path, "w", encoding="utf-8") as f: f.write("{壞掉")
    check("P4 檔案壞掉不會讓機器人起不來，當作空的", Library(path).users == {})
    with open(path, "w", encoding="utf-8") as f: f.write('{"users": {"1": "bad", "2": {"type": "folder", "id": "root", "name": "", "children": []}}}')
    check("P5 只留格式對的人", list(Library(path).users) == ["2"])

# ============ 拖曳：排序與搬歌（2.0.1）============
r = T.new_root()
a, b, c = (T.add_playlist(r, "root", n, [song(i) for i in range(3)]) for n in "abc")
f = T.add_folder(r, "root", "F")
names = lambda: [x["name"] for x in r["children"]]
T.move(r, [c["id"]], "root", 0)
check("D1 同一層拖到最前面 = 重新排序", names() == ["c", "a", "b", "F"], names())
T.move(r, [a["id"]], "root", 99)
check("D2 index 太大就放到最後", names() == ["c", "b", "F", "a"], names())
T.move(r, [b["id"], c["id"]], "root", 1)
check("D3 多個一起排序，依序排在一起", names() == ["F", "b", "c", "a"], names())
check("D4 搬進別的資料夾（沒有 index）= 放到最後", T.move(r, [a["id"]], f["id"]) == 1 and [x["name"] for x in f["children"]] == ["a"] and "a" not in names())
T.move(r, [b["id"]], f["id"], 0)
check("D5 搬進資料夾並指定位置", [x["name"] for x in f["children"]] == ["b", "a"])
T.reorder_song(r, c["id"], 2, 0)
check("D6 歌單內排序：第 3 首搬到最前面", [s["title"] for s in c["songs"]] == ["歌2", "歌0", "歌1"], [s["title"] for s in c["songs"]])
T.reorder_song(r, c["id"], 9, 0); T.reorder_song(r, c["id"], 0, 99)
check("D7 位置亂給不會壞（超出範圍的被夾住或略過）", [s["title"] for s in c["songs"]] == ["歌0", "歌1", "歌2"] or len(c["songs"]) == 3, [s["title"] for s in c["songs"]])
before = T.count_songs(r)
check("D8 搬歌到另一張歌單：數量不變，放到最後", T.move_songs(r, c["id"], [0, 2], b["id"]) == 2 and len(c["songs"]) == 1 and len(b["songs"]) == 5 and T.count_songs(r) == before)
check("D9 搬到自己或不存在的歌單：不動 / 報錯", T.move_songs(r, c["id"], [0], c["id"]) == 0 and raises(T.move_songs, r, c["id"], [0], "nope"))
big = T.new_root(); bp = T.add_playlist(big, "root", "big", [song(i) for i in range(2000)]); bq = T.add_playlist(big, "root", "q", [])
import time as _t; t0 = _t.perf_counter(); T.move_songs(big, bp["id"], list(range(1500)), bq["id"])
check("D10 一次搬 1500 首很快（不會每首重建集合）", len(bq["songs"]) == 1500 and len(bp["songs"]) == 500 and _t.perf_counter() - t0 < 0.5, _t.perf_counter() - t0)

print(f"{sum(res)}/{len(res)} 通過", flush=True)
sys.exit(0 if all(res) else 1)
