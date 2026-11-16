"""專屬連結入口（verify 模式，2.0 起唯一的入口）：成員用 /help 連結進來、加歌／刪除／排序、暱稱、頻道清單、沒憑證的人什麼都不能做
The personal-link entry (verify mode, the only way in since 2.0): members arrive with their /help link, add / remove / reorder, nicknames, channel list, and someone without a token can do nothing

用 tests/run_all.py 或 tests/run_relay.py 執行 / run it with tests/run_all.py or tests/run_relay.py
"""
import asyncio, aiohttp, json, time
BASE = "http://127.0.0.1:8766"; DBG = "http://127.0.0.1:8767"; GID = 777
res = []
def check(n, ok, d=""): res.append(bool(ok)); print(("PASS" if ok else "FAIL"), n, str(d)[:170], flush=True)

class Client:
    def __init__(self, s, token=None, headers=None, name=None):
        self.s, self.token, self.headers, self.name = s, token, headers or {}, name
        self.st = {}; self.toasts = []; self.msgs = []; self.err = None
    async def open(self):
        q = []
        if self.token: q.append(f"t={self.token}")
        if self.name: q.append(f"n={self.name}")
        self.ws = await self.s.ws_connect(f"{BASE.replace('http','ws')}/ws/{GID}" + ("?" + "&".join(q) if q else ""), headers=self.headers)
        self.task = asyncio.create_task(self._pump()); await asyncio.sleep(0.4); return self
    async def _pump(self):
        async for m in self.ws:
            if m.type != aiohttp.WSMsgType.TEXT: continue
            d = json.loads(m.data); self.msgs.append(d)
            if d["type"] == "state": self.st = d["data"]
            elif d["type"] == "toast": self.toasts.append(d["text"])
            elif d["type"] == "error": self.err = d
    async def send(self, **o): await self.ws.send_str(json.dumps(o))
    async def until(self, pred, t=40):
        e = time.time() + t
        while time.time() < e:
            if self.st and pred(self.st): return self.st
            await asyncio.sleep(0.1)
        raise TimeoutError(str(self.st.get("players")))
    async def close(self): self.task.cancel(); await self.ws.close()

async def info(s):
    async with s.get(f"{DBG}/info") as r: return (await r.json())["workers"]
async def tok(s, uid):
    async with s.get(f"{DBG}/token", params={"u": uid}) as r: return (await r.json())["t"]
BILI = "https://www.bilibili.com/video/av55185686"
# 模擬"經過通道／從別台電腦"：Host 不是 localhost，並帶代理標頭（沒有連結憑證的人進不來）
REMOTE = {"Host": "friend.example.com", "X-Forwarded-For": "203.0.113.9"}

async def main():
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{DBG}/move", params={"u": 1004}) as r: await r.read()     # 兩位成員都不在任何語音頻道 / neither member sits in a voice channel
        g1 = await Client(s, token=await tok(s, 1003), headers=REMOTE).open()
        g2 = await Client(s, token=await tok(s, 1004), headers=REMOTE).open()
        check("1a 用 /help 連結的成員：進得來", g1.err is None and g1.st.get("guild"), g1.err)
        check("1b 成員：能控制、但不是主人也不是擁有者", g1.st["me"]["can_control"] is True and not g1.st["me"]["host"] and not g1.st["me"]["owner"], g1.st["me"])
        check("1c 顯示的是連結裡的 Discord 暱稱", g1.st["me"]["name"] == "小美(不在語音)", g1.st["me"]["name"])
        check("1d 快照帶有語音頻道清單", [c["name"] for c in g1.st["channels"]] == ["放鬆休息", "肝到世界盡頭", "趕工阿", "會議室"], [c["name"] for c in g1.st["channels"]])
        bad = await Client(s, token="garbage.token", headers=REMOTE).open()
        check("1e 憑證亂寫：只是未驗證，不能控制", bad.st["me"]["pending"] is True and bad.st["me"]["can_control"] is False, bad.st.get("me"))
        none = await Client(s, headers=REMOTE, name="路人").open()
        check("1f 完全沒有憑證（知道網址也一樣）：不能控制，並被告知要用 /help 連結", none.st["me"]["pending"] is True and none.st["me"]["can_control"] is False and "/help" in none.st["me"]["reason"], none.st.get("me"))
        n0 = len(none.toasts); await none.send(type="add", query=BILI, channel="502"); await asyncio.sleep(0.6)
        check("1g 沒有憑證的人送加歌指令：被擋下，播放器沒動", len(none.toasts) > n0 and all(w["vc"] is None for w in await info(s)), none.toasts[-1:])
        async with s.get(f"{BASE}/api/guilds", headers=REMOTE) as r:
            check("1h 遠端不能列出伺服器清單", r.status == 403, r.status)
        await bad.close(); await none.close()

        n = len(g1.toasts)
        await g1.send(type="add", query=BILI); await asyncio.sleep(0.8)
        check("2a 沒選頻道、也沒有播放器：提示先選頻道", len(g1.toasts) > n and "選一個語音頻道" in g1.toasts[-1], g1.toasts[-1:])

        # 3. 成員不在任何語音頻道，也能指定"加到哪個頻道"；兩個人同時加到不同頻道
        await asyncio.gather(g1.send(type="add", query=BILI, channel="502"), g2.send(type="add", query=BILI, channel="503"))
        t0 = time.time()
        while time.time() - t0 < 40:
            w = await info(s)
            if w[0]["vc"] is not None and w[1]["vc"] is not None: break
            await asyncio.sleep(0.4)
        vcs = [x["vc"] for x in w]
        check("3a 成員指定頻道：播放器進去那些頻道（不同頻道、不同機器人）", {w[0]["vc"], w[1]["vc"]} == {502, 503} and w[0]["vc"] != w[1]["vc"], vcs)
        await g1.until(lambda st: all(c["pid"] for c in st["channels"] if c["name"] in ("肝到世界盡頭", "趕工阿")) and len(st["players"]) == 2 and all(p["title"] for p in st["players"]), 60); await asyncio.sleep(4)
        ch = {c["name"]: c["pid"] for c in g1.st["channels"]}
        check("3b 頻道清單標出誰有播放器", ch["肝到世界盡頭"] and ch["趕工阿"] and ch["放鬆休息"] is None, ch)

        # 4. 成員可以控制"所有"頻道，不受所在頻道限制
        pids = [p["pid"] for p in g1.st["players"]]
        for pid in pids:
            await g1.send(type="select", pid=pid); await g1.until(lambda st, pid=pid: st["selected"] == pid and st["current"] and not st["current"]["loading"], 60)
            before = g1.st["paused"]
            await g1.send(type="toggle_pause"); await asyncio.sleep(0.6)
            await g1.until(lambda st: st["paused"] != before, 5)
            await g1.send(type="toggle_pause"); await asyncio.sleep(0.4)
        check("4a 成員可以暫停／繼續每一個頻道的播放器", True)
        await g1.send(type="select", pid=pids[0]); await asyncio.sleep(0.3)
        n0 = len(g1.st["queue"]) + 1
        await g2.send(type="select", pid=pids[0]); await asyncio.sleep(0.3)
        await g2.send(type="add", query=BILI); await asyncio.sleep(5)       # g2 沒選頻道、但已選播放器 -> 加到該播放器
        await g1.until(lambda st: len(st["queue"]) + 1 > n0, 20)
        check("4b 另一個成員可以替別的頻道的播放器加歌", len(g1.st["queue"]) + 1 == n0 + 1, f"{n0} -> {len(g1.st['queue']) + 1}")

        # 5. 全部忙碌（只有 2 個播放器）
        n = len(g1.toasts)
        await g1.send(type="add", query=BILI, channel="504"); await asyncio.sleep(1.0)
        check("5a 全部播放器都忙：明確告知", len(g1.toasts) > n and "都在使用中" in g1.toasts[-1], g1.toasts[-1:])

        # 6. 音質：成員可以改
        await g1.send(type="quality", kbps=320); await g1.until(lambda st: st["quality"]["kbps"] == 320, 8)
        check("6a 成員可以切換音質", g1.st["quality"]["kbps"] == 320)
        await g1.send(type="quality", kbps=192); await asyncio.sleep(0.5)

        # 7. 底線：Bilibili 帳號仍然只限擁有者／本機
        n = len(g1.toasts)
        await g1.send(type="bili_login_start"); await asyncio.sleep(0.6)
        check("7a 成員不能發起 Bilibili 登入", len(g1.toasts) > n and "擁有者" in g1.toasts[-1], g1.toasts[-1:])
        n = len(g1.toasts)
        await g1.send(type="bili_logout"); await asyncio.sleep(0.6)
        check("7b 成員不能登出 Bilibili", len(g1.toasts) > n and "擁有者" in g1.toasts[-1], g1.toasts[-1:])
        check("7c 成員看不到帳號細節、也沒有管理入口", g1.st["bili"]["can_manage"] is False and "name" not in g1.st["bili"], g1.st["bili"])
        owner = await Client(s, token=await tok(s, 9001), headers=REMOTE).open()
        check("7d 擁有者（用 /help 的擁有者連結）：有管理入口", owner.st["bili"]["can_manage"] is True and owner.st["me"]["owner"] is True)
        local = await Client(s).open()
        check("7e 本機直接開：是主人、有管理入口", local.st["me"]["host"] is True and local.st["bili"]["can_manage"] is True)
        for c in (g1, g2, owner, local): await c.close()
    print(f"\n總結：{sum(res)}/{len(res)} 通過")
asyncio.run(asyncio.wait_for(main(), 240))

