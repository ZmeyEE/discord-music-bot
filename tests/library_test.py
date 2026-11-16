"""我的歌單（走真的看板與 WebSocket）：存歌單、資料夾、搬移、刪除、各人隔離、播放與資料夾循環
The library through the real dashboard and WebSocket: save playlists, folders, move, delete, per-person isolation, playing and folder loops

用 tests/run_all.py 執行 / run it with tests/run_all.py
"""
import asyncio, aiohttp, json, time
BASE = "http://127.0.0.1:8766"; DBG = "http://127.0.0.1:8767"; GID = 777
REMOTE = {"Host": "friend.example.com", "X-Forwarded-For": "203.0.113.9"}
res = []
def check(n, ok, d=""): res.append(bool(ok)); print(("PASS" if ok else "FAIL"), n, str(d)[:200], flush=True)

class Client:
    def __init__(self, s, token=None, headers=None):
        self.s, self.token, self.headers = s, token, headers or {}
        self.st, self.toasts, self.lib, self.songs, self.err = {}, [], None, None, None
    async def open(self):
        self.ws = await self.s.ws_connect(f"{BASE.replace('http', 'ws')}/ws/{GID}" + (f"?t={self.token}" if self.token else ""), headers=self.headers)
        self.task = asyncio.create_task(self._pump()); await asyncio.sleep(0.4); return self
    async def _pump(self):
        async for m in self.ws:
            if m.type != aiohttp.WSMsgType.TEXT: continue
            d = json.loads(m.data)
            if d["type"] == "state": self.st = d["data"]
            elif d["type"] == "toast": self.toasts.append(d["text"])
            elif d["type"] == "library": self.lib = d["data"]["tree"]
            elif d["type"] == "library_songs": self.songs = d["data"]
            elif d["type"] == "error": self.err = d
    async def act(self, wait=0.5, **o):
        """送出一個操作，回傳這段時間收到的提示 / send an action, return the toasts that arrived meanwhile"""
        n = len(self.toasts)
        await self.ws.send_str(json.dumps(o)); await asyncio.sleep(wait)
        return self.toasts[n:]
    async def until(self, pred, t=20):
        e = time.time() + t
        while time.time() < e:
            if self.st and pred(self.st): return self.st
            await asyncio.sleep(0.1)
        raise TimeoutError(str(self.st.get("queue_total")))
    async def close(self): self.task.cancel(); await self.ws.close()

async def dbg(s, path, **q):
    async with s.get(f"{DBG}{path}", params=q) as r: return await r.json()
async def tok(s, uid): return (await dbg(s, "/token", u=uid))["t"]
def names(nodes): return [n["name"] for n in nodes]
def find(tree, name):
    for n in (tree or {}).get("children", []):
        if n["name"] == name: return n
        if n["type"] == "folder":
            f = find(n, name)
            if f: return f
    return None
def total(st): return st["queue_total"] + (1 if st["current"] else 0)

async def main():
    async with aiohttp.ClientSession() as s:
        await dbg(s, "/move", u=1004)                      # 1003、1004 都不在語音頻道 / neither 1003 nor 1004 is in a voice channel
        a = await Client(s, token=await tok(s, 1003), headers=REMOTE).open()
        b = await Client(s, token=await tok(s, 1004), headers=REMOTE).open()
        nobody = await Client(s, headers=REMOTE).open()
        owner = await Client(s, token=await tok(s, 9001), headers=REMOTE).open()
        local = await Client(s).open()

        # 1. 沒有身分的人不能碰歌單 / someone without an identity can't touch the library
        t = await nobody.act(type="lib_get")
        check("1a 沒有連結的人：拿不到歌單", nobody.lib is None, t)
        await nobody.act(type="lib_playlist", name="偷偷建")
        check("1b 沒有連結的人不能建立東西", nobody.lib is None)

        # 2. 把待播存成歌單 / save the queue as a playlist
        await dbg(s, "/fill", n=12, clear=1)
        await a.act(type="select", pid="5000")
        await a.until(lambda st: st.get("queue_total", 0) >= 12 and st.get("selected") == "5000")
        ids = [x["id"] for x in a.st["queue"][:4]]
        t = await a.act(type="lib_save", name="抒情", ids=ids)
        pl = find(a.lib, "抒情")
        check("2a 選 4 首存成歌單", pl and pl["count"] == 4 and pl["type"] == "playlist" and t and "4" in t[0], (a.lib, t))
        await a.act(type="lib_save", name="全部")
        pl = find(a.lib, "全部")
        check("2b 沒選就是存整份待播", pl and pl["count"] == 12, a.lib)
        await a.act(type="lib_open", id=find(a.lib, "抒情")["id"])
        check("2c 打開歌單拿得到每首歌的連結", a.songs and a.songs["total"] == 4 and all(x["url"].startswith("https://") for x in a.songs["songs"]), a.songs and a.songs["total"])

        # 3. 各人隔離 / isolation
        await b.act(type="lib_get")
        check("3a 另一個人看不到別人的歌單", b.lib is not None and b.lib["children"] == [], b.lib)
        await a.act(type="lib_get")
        mine = find(a.lib, "抒情")["id"]
        await b.act(type="lib_delete", ids=[mine])
        await a.act(type="lib_get")
        check("3b 另一個人刪不到別人的歌單", find(a.lib, "抒情") is not None)
        await b.act(type="lib_open", id=mine)
        check("3c 另一個人打不開別人的歌單", b.songs is None, b.songs)

        # 4. 資料夾：多選建立、巢狀、改名、搬移 / folders
        ids2 = [find(a.lib, "抒情")["id"], find(a.lib, "全部")["id"]]
        await a.act(type="lib_folder", name="華語", ids=ids2)
        check("4a 多選歌單建立資料夾", names(a.lib["children"]) == ["華語"] and names(find(a.lib, "華語")["children"]) == ["抒情", "全部"], a.lib)
        await a.act(type="lib_folder", name="日語", parent="root")
        await a.act(type="lib_folder", name="動漫", parent=find(a.lib, "日語")["id"])
        check("4b 資料夾裡可以再放資料夾", names(find(a.lib, "日語")["children"]) == ["動漫"])
        await a.act(type="lib_move", ids=[find(a.lib, "全部")["id"]], to=find(a.lib, "動漫")["id"])
        check("4c 搬進深一層的資料夾", names(find(a.lib, "動漫")["children"]) == ["全部"] and names(find(a.lib, "華語")["children"]) == ["抒情"])
        t = await a.act(type="lib_move", ids=[find(a.lib, "日語")["id"]], to=find(a.lib, "動漫")["id"])
        check("4d 不能把資料夾搬進自己底下", t and "自己" in t[0], t)
        await a.act(type="lib_get")                          # 出錯時伺服器只回提示，所以重新拿一次樹 / on an error only a toast comes back, so fetch the tree again
        await a.act(type="lib_rename", id=find(a.lib, "華語")["id"], name="國語")
        check("4e 改名", find(a.lib, "國語") and not find(a.lib, "華語"))
        check("4f 資料夾的歌數是底下全部的", find(a.lib, "日語")["count"] == 12 and find(a.lib, "國語")["count"] == 4, (find(a.lib, "日語")["count"], find(a.lib, "國語")["count"]))

        # 5. 播放（測試用的歌是假網址，放進去不久就會因為播不出來被略過，所以看回覆的提示和當下的待播，不等數量穩定）
        # play (the test songs have fake URLs and get skipped soon after because they can't play, so look at the reply and the queue right then)
        t = await a.act(wait=8.0, type="lib_play", id=find(a.lib, "國語")["id"], when="replace")
        check("5a 播放資料夾（取代）：提示放進 4 首", t and "4 首" in t[0], t)
        t = await a.act(wait=20.0, type="lib_play", id=find(a.lib, "動漫")["id"], when="end")     # 12 首假網址要一首一首失敗過去，要等一陣子 / 12 fake URLs fail one by one, which takes a while
        check("5b 播放（加到最後）：提示放進 12 首", t and "12 首" in t[0], t)

        # 6. 資料夾循環（伺服器端的"下一輪"）/ folder loops (the server-side "next round")
        info = await dbg(s, "/scope_test", u=1002)           # 用另一個人的歌單測，不動 1003 的 / uses another person, 1003's library stays untouched
        check("6a 資料夾循環：播完再放同一個資料夾", info["folder"]["same"], info)
        check("6b 跨資料夾循環：播完換同一層的下一個資料夾，到底繞回第一個", info["folders"]["order"] == info["folders"]["expect"], info["folders"])
        check("6c 資料夾被刪掉就不再循環", info["gone"] is None, info)
        await a.act(type="lib_get")

        # 7. 移除、刪除、存檔 / remove, delete, persistence
        await a.act(type="lib_folder", name="甲", parent="root")
        await a.act(type="lib_folder", name="乙", parent="root")
        for name in ("甲", "乙"):
            await dbg(s, "/libseed", u=1003, n=2, name=name + "歌", parent=find(a.lib, name)["id"])
        await a.act(type="lib_get")
        await a.act(type="lib_play", id=find(a.lib, "甲")["id"], when="replace", scope="folders")
        sc = await dbg(s, "/scope_of")
        check("7a 跨資料夾循環播放：記住循環範圍", sc and sc["mode"] == "folders" and sc["node"] in (find(a.lib, "甲")["id"], find(a.lib, "乙")["id"]), sc)
        await a.act(type="clear")
        check("7b 清空待播 = 不再循環", await dbg(s, "/scope_of") is None)
        await a.act(type="lib_play", id=find(a.lib, "乙")["id"], when="replace")
        check("7c 沒選循環就不記範圍", await dbg(s, "/scope_of") is None)
        await a.act(type="lib_delete", ids=[find(a.lib, "日語")["id"], find(a.lib, "甲")["id"], find(a.lib, "乙")["id"]])
        check("7d 刪資料夾連同裡面的", not find(a.lib, "日語") and not find(a.lib, "全部") and not find(a.lib, "甲歌 000"), a.lib)
        await a.act(type="lib_remove_songs", playlist=find(a.lib, "抒情")["id"], indexes=[0, 1])
        check("7e 從歌單移除歌", find(a.lib, "抒情")["count"] == 2, find(a.lib, "抒情"))
        saved = await dbg(s, "/libfile", u=1003)
        check("7f 已經寫進檔案", saved["playlists"] >= 1 and saved["songs"] == 2, saved)

        # 8. 擁有者與本機共用擁有者的歌單 / the owner and the local machine share the owner's library
        await dbg(s, "/libseed", u=9001, n=5, name="擁有者的", reset=1)
        await owner.act(type="lib_get"); await local.act(type="lib_get")
        check("8a 擁有者看得到自己的", find(owner.lib, "擁有者的") is not None, owner.lib)
        check("8b 本機直接開 = 擁有者的歌單", find(local.lib, "擁有者的") is not None, local.lib)
        check("8c 擁有者看不到別人的", find(owner.lib, "抒情") is None)

        # 9. 亂來的輸入 / bad input
        t = await a.act(type="lib_play", id="不存在", when="end")
        check("9a 播放不存在的項目：有明確提示", t and "找不到" in t[0], t)
        t = await a.act(type="lib_folder", name="x" * 500, parent="不存在")
        check("9b 資料夾建在不存在的地方：提示而不是崩潰", t, t)
        await a.act(type="lib_move", ids="not-a-list", to="root")
        await a.act(type="lib_open", id="root", offset="abc")
        check("9c 格式亂掉也不會崩潰，連線還在", not a.ws.closed and a.err is None)
        for c in (a, b, nobody, owner, local): await c.close()
    print(f"\n總結：{sum(res)}/{len(res)} 通過")
asyncio.run(asyncio.wait_for(main(), 200))
