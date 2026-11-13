"""卡頓偵測整合測試（harness：3 個機器人、4 個語音頻道；用假時鐘快轉 5 秒區間）"""
import asyncio, aiohttp, json, time
BASE = "http://127.0.0.1:8766"; DBG = "http://127.0.0.1:8767"; GID = 777
res = []
def check(n, ok, d=""): res.append(bool(ok)); print(("PASS" if ok else "FAIL"), n, str(d)[:230], flush=True)
BILI = "https://www.bilibili.com/video/av55185686"

class Client:
    def __init__(self, s): self.s = s; self.st = {}; self.toasts = []
    async def open(self):
        self.ws = await self.s.ws_connect(f"{BASE.replace('http','ws')}/ws/{GID}")
        self.task = asyncio.create_task(self._pump()); await asyncio.sleep(0.6); return self
    async def _pump(self):
        async for m in self.ws:
            if m.type != aiohttp.WSMsgType.TEXT: continue
            d = json.loads(m.data)
            if d["type"] == "state": self.st = d["data"]
            elif d["type"] == "toast": self.toasts.append(d["text"])
    async def send(self, **o): await self.ws.send_str(json.dumps(o))
    async def until(self, pred, t=40):
        e = time.time() + t
        while time.time() < e:
            if pred(): return True
            await asyncio.sleep(0.15)
        return False
async def dbg(s, path, **p):
    async with s.get(f"{DBG}/{path}", params=p) as r: return await r.json()

async def add_and_load(c, ch):
    """加一首歌到某頻道，等它真的載入完成、開始播放"""
    before = {p["pid"] for p in c.st.get("players", [])}
    await c.send(type="add", query=BILI, channel=ch)
    ok = await c.until(lambda: {p["pid"] for p in c.st.get("players", [])} - before, 60)
    if not ok: return False
    new = ({p["pid"] for p in c.st["players"]} - before).pop()
    await c.send(type="select", pid=new)
    return await c.until(lambda: c.st.get("selected") == new and c.st.get("current") and not c.st["current"]["loading"], 90)

async def main():
    async with aiohttp.ClientSession() as s:
        c = await Client(s).open()
        ok1 = await add_and_load(c, "501"); t = await dbg(s, "tick", n=14)       # 1 個頻道，順 70 秒
        ok2 = await add_and_load(c, "502"); t = await dbg(s, "tick", n=14)       # 2 個頻道，順 70 秒
        ok3 = await add_and_load(c, "503")                                         # 第 3 個頻道加入
        check("H0 三個頻道依序加入並開始播放（每加一個都先觀察一段）", ok1 and ok2 and ok3 and t["k"] == 2, (ok1, ok2, ok3, t["k"]))
        check("H1 一開始沒有任何上限、沒有公告（分身不設限）", c.st["limit"]["max"] == 3 and c.st["limit"]["notice"] is None, c.st["limit"])

        # ---- 濾波：偶爾一下不算 ----
        t = await dbg(s, "tick", n=1, w="2", ev=6)
        t = await dbg(s, "tick", n=14)
        check("H2 一次爆發的卡頓（同一個 5 秒內 6 次）：濾掉，不停任何頻道", t["removed"] is None and t["streaming"] == 3, t)

        # ---- 持續卡頓、而且是第 3 個頻道加入後才出現：停最後加入的 ----
        t = await dbg(s, "tick", n=40, w="0,1,2", ev=1)
        rm = t["removed"]
        check("H3 持續卡頓、加入前很順：停掉『最後加入』的那個（503 趕工阿），不是別的", rm and rm["channel"] == "趕工阿" and rm["remaining"] == 2, rm)
        check("H3b 判斷依據：加入前很順的秒數、加入後的卡頓次數都有帶出來", rm and rm["base"] >= 40 and rm["events"] >= 4, rm)
        check("H3c 不是一卡就停：卡頓持續了至少 20 秒才動手（≥ 5 個 5 秒區間）", t["ticks"] >= 5, t["ticks"])
        short = await dbg(s, "tick", n=0)     # 只是確認端點正常
        sent = t["sent"]; chans = {n for n, _ in sent}
        check("H4 公告送到每個語音頻道的聊天室（含被停掉的那個）", {"放鬆休息", "肝到世界盡頭", "趕工阿"} <= chans, chans)
        txt = sent[-1][1] if sent else ""
        check("H4b 公告內容：說明是哪個頻道、原因、已停止、剩幾個、10 分鐘不加新的", all(k in txt for k in ("趕工阿", "加入之後才開始", "原因：", "已停止", "還有 2 個頻道", "10 分鐘")), txt[:120])
        info = await dbg(s, "info")
        vcs = [w["vc"] for w in info["workers"]]
        check("H5 只停了一個：被停的離開語音頻道，另外兩個照常在播", vcs.count(None) == 1 and vcs[2] is None and vcs[0] and vcs[1], vcs)
        await c.until(lambda: c.st["limit"]["notice"])
        check("H6 看板快照帶有公告", "趕工阿" in (c.st["limit"]["notice"] or ""), c.st["limit"])

        # ---- 緩衝：停掉之後如果還是卡，不會繼續停 ----
        t = await dbg(s, "tick", n=60, w="0,1", ev=1)
        check("H7 停掉後如果還是卡（原因不在新加入的）：不會繼續停，不會停光", t["removed"] is None and t["streaming"] == 2, t)

        # ---- 停掉之後 10 分鐘不加新頻道；期滿恢復 ----
        c2 = await Client(s).open(); n0 = len(c2.toasts)
        await c2.send(type="add", query=BILI, channel="504"); await asyncio.sleep(1.5)
        check("H8 剛停掉的期間：新頻道不派分身，並說明原因", len(c2.toasts) > n0 and "暫時不再增加" in c2.toasts[-1], c2.toasts[-1:])
        n1 = len(c2.toasts)
        await c2.send(type="add", query=BILI, channel="501"); await asyncio.sleep(2.5)
        check("H9 已經有播放器的頻道仍然可以繼續加歌", not any("暫時不再增加" in x for x in c2.toasts[n1:]), c2.toasts[n1:])
        lim = await dbg(s, "expire_hold")
        check("H10 期滿後上限恢復成機器人總數（不設限）", lim["limit"] == 3, lim)
        n2 = len(c2.toasts)
        await c2.send(type="add", query=BILI, channel="504"); await asyncio.sleep(2.5)
        ok = await c.until(lambda: any(p["name"] == "會議室" for p in c.st.get("players", [])), 30)
        check("H11 期滿後可以再開新頻道（把停掉的分身派去 504 會議室）", ok and not any("暫時不再增加" in x for x in c2.toasts[n2:]), [p["name"] for p in c.st.get("players", [])])
    print(f"\n總結：{sum(res)}/{len(res)} 通過")
asyncio.run(asyncio.wait_for(main(), 300))
