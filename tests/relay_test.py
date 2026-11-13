"""中繼站測試：relay(8770) <-- harness 內的 RelayClient；瀏覽器經由 relay 連線"""
import asyncio, aiohttp, json, os, subprocess, sys, time
RELAY = "http://127.0.0.1:8770"; GID = 777
KEY = os.environ["RELAY_KEY"]
res = []
def check(n, ok, d=""): res.append(bool(ok)); print(("PASS" if ok else "FAIL"), n, str(d)[:170], flush=True)

class Client:
    def __init__(self, s, token=None, name=None, base=RELAY):
        self.s, self.token, self.name, self.base = s, token, name, base
        self.st = {}; self.toasts = []; self.msgs = []; self.err = None; self.closed = False
    async def open(self):
        q = [x for x in (f"t={self.token}" if self.token else "", f"n={self.name}" if self.name else "") if x]
        self.ws = await self.s.ws_connect(f"{self.base.replace('http','ws')}/ws/{GID}" + ("?" + "&".join(q) if q else ""))
        self.task = asyncio.create_task(self._pump()); await asyncio.sleep(0.8); return self
    async def _pump(self):
        async for m in self.ws:
            if m.type != aiohttp.WSMsgType.TEXT: continue
            d = json.loads(m.data); self.msgs.append(d)
            if d["type"] == "state": self.st = d["data"]
            elif d["type"] == "toast": self.toasts.append(d["text"])
            elif d["type"] == "error": self.err = d
        self.closed = True
    async def send(self, **o): await self.ws.send_str(json.dumps(o))
    async def until(self, pred, t=40):
        e = time.time() + t
        while time.time() < e:
            if self.st and pred(self.st): return self.st
            await asyncio.sleep(0.15)
        raise TimeoutError(str(self.st.get("players")))
    async def close(self): self.task.cancel(); await self.ws.close()

async def tok(s, uid):
    async with s.get(f"http://127.0.0.1:8767/token", params={"u": uid}) as r: return (await r.json())["t"]
BILI = "https://www.bilibili.com/video/av55185686"

async def fake_worker(s, key, name):
    """假的播放端：用給定的金鑰嘗試連到中繼站"""
    import hmac, hashlib
    try:
        ws = await s.ws_connect(f"{RELAY.replace('http','ws')}/relay")
        ch = await ws.receive_json()
        await ws.send_json({"t": "auth", "proof": hmac.new(key.encode(), ch["nonce"].encode(), hashlib.sha256).hexdigest()})
        m = await asyncio.wait_for(ws.receive(), 5)
        ok = m.type == aiohttp.WSMsgType.TEXT and json.loads(m.data).get("t") == "ready"
        await ws.close(); return ok, m.type.name
    except Exception as e:
        return False, repr(e)[:60]

async def main():
    async with aiohttp.ClientSession() as s:
        # ===== 1. 基本轉送 =====
        g1 = await Client(s, name="阿花").open()
        check("1a 瀏覽器經中繼站連上，收到來自家裡機器人的狀態", g1.st.get("guild", {}).get("name") == "測試伺服器", g1.err)
        check("1b 開放模式：以訪客身分（不是主人）", g1.st["me"]["host"] is False and g1.st["me"]["can_control"] and g1.st["me"]["name"] == "阿花", g1.st["me"])
        async with s.get(f"{RELAY}/api/guilds") as r: gl = await r.json()
        check("1c /api/guilds 由中繼站回答（開放模式）", gl and gl[0]["name"] == "測試伺服器", gl)
        async with s.get(f"{RELAY}/healthz") as r: hz = await r.json()
        check("1d /healthz 回報播放端在線", hz["worker_online"] is True and hz["browsers"] >= 1, hz)
        async with s.get(f"{RELAY}/") as r: check("1e 中繼站自己提供看板頁面", r.status == 200 and "音樂看板" in await r.text())

        # ===== 2. 操作經中繼站送回家裡執行 =====
        await g1.send(type="add", query=BILI, channel="501")
        await g1.until(lambda st: st["current"] and not st["current"]["loading"], 60)
        check("2a 經中繼站加歌：家裡的播放器真的開始播放", g1.st["channel"] == "放鬆休息" and g1.st["current"]["requester"] == "阿花", g1.st["channel"])
        await g1.send(type="toggle_pause"); await g1.until(lambda st: st["paused"], 8)
        check("2b 經中繼站暫停", g1.st["paused"] is True)
        await g1.send(type="toggle_pause"); await asyncio.sleep(0.5)
        g2 = await Client(s, name="阿強").open()
        await g1.send(type="loop", mode="single"); await g2.until(lambda st: st["loop"] == "single", 8)
        check("2c 一個瀏覽器的操作，另一個瀏覽器即時看到", g2.st["loop"] == "single")

        # ===== 3. 底線：Bilibili 帳號只限擁有者 =====
        n = len(g1.toasts); await g1.send(type="bili_login_start"); await asyncio.sleep(0.8)
        check("3a 訪客經中繼站不能發起 Bilibili 登入", len(g1.toasts) > n and "擁有者" in g1.toasts[-1], g1.toasts[-1:])
        check("3b 經中繼站的連線永遠不是『本機主人』", g1.st["bili"]["can_manage"] is False and g2.st["me"]["host"] is False)
        owner = await Client(s, token=await tok(s, 9001)).open()
        check("3c 擁有者連結經中繼站：有管理入口", owner.st["bili"]["can_manage"] is True and owner.st["me"]["owner"] is True)

        # ===== 4. 金鑰驗證 =====
        ok, why = await fake_worker(s, "wrong-key-wrong-key-wrong", "x")
        check("4a 錯誤的金鑰：被拒絕", ok is False, why)
        async with s.get(f"{RELAY}/healthz") as r: hz = await r.json()
        check("4b 假播放端沒有擠掉真的播放端", hz["worker_online"] is True and g1.st.get("guild"))
        await g1.send(type="loop", mode="off"); await g2.until(lambda st: st["loop"] == "off", 8)
        check("4c 被拒絕後，真正的播放端仍然正常運作", g2.st["loop"] == "off")

        # ===== 5. 限流：一個瀏覽器狂送訊息，不能把家裡的機器人灌爆 =====
        before = len(g1.msgs)
        for _ in range(400): await g1.send(type="shuffle")
        await asyncio.sleep(2.5)
        got = len(g1.msgs) - before
        check("5a 狂送 400 則：中繼站只轉送約 burst 數量", got < 200, f"收到 {got} 則回應")
        check("5b 限流後中繼站與機器人仍然健康", (await (await s.get(f'{RELAY}/healthz')).json())["worker_online"])

        # ===== 6. 播放端離線與自動恢復 =====
        await s.get("http://127.0.0.1:8767/shutdown")   # 關掉播放端 / stop the player side
        t0 = time.time()
        while time.time() - t0 < 10 and not g1.err: await asyncio.sleep(0.3)
        check("6a 播放端斷線：瀏覽器收到明確的離線通知（而且連線沒被關掉）", g1.err and g1.err["code"] == "offline" and not g1.closed, g1.err)
        async with s.get(f"{RELAY}/healthz") as r: hz = await r.json()
        check("6b /healthz 回報離線，瀏覽器數量不變", hz["worker_online"] is False and hz["browsers"] >= 3, hz)
        async with s.get(f"{RELAY}/api/guilds") as r: check("6c 離線時 /api/guilds 回空清單", await r.json() == [])
        for c in (g1, g2, owner): await c.close()
    print(f"\n總結：{sum(res)}/{len(res)} 通過")
asyncio.run(asyncio.wait_for(main(), 300))
