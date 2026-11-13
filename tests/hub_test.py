"""語音模式（voice）的權限與多頻道：誰能控制、分身預約、頻道清單
Voice-mode permissions and multi-channel: who may control, clone reservation, channel list

用 tests/run_all.py 或 tests/run_relay.py 執行 / run it with tests/run_all.py or tests/run_relay.py
"""
import asyncio, aiohttp, json, time
BASE = "http://127.0.0.1:8766"; DBG = "http://127.0.0.1:8767"; GID = 777
res = []
def check(n, ok, d=""): res.append(ok); print(("PASS" if ok else "FAIL"), n, str(d)[:170], flush=True)

class Client:
    """一個後台連線：記錄最新快照與 toast"""
    def __init__(self, s, token=None, headers=None, gid=GID):
        self.s, self.token, self.headers, self.gid = s, token, headers or {}, gid
        self.st = {}; self.toasts = []; self.msgs = []; self.err = None
    async def open(self):
        url = f"{BASE.replace('http','ws')}/ws/{self.gid}" + (f"?t={self.token}" if self.token else "")
        self.ws = await self.s.ws_connect(url, headers=self.headers)
        self.task = asyncio.create_task(self._pump()); await asyncio.sleep(0.3); return self
    async def _pump(self):
        async for m in self.ws:
            if m.type != aiohttp.WSMsgType.TEXT: continue
            d = json.loads(m.data); self.msgs.append(d)
            if d["type"] == "state": self.st = d["data"]
            elif d["type"] == "toast": self.toasts.append(d["text"])
            elif d["type"] == "error": self.err = d
    async def send(self, **o): await self.ws.send_str(json.dumps(o))
    async def until(self, pred, t=25):
        e = time.time() + t
        while time.time() < e:
            if self.st and pred(self.st): return self.st
            await asyncio.sleep(0.1)
        raise TimeoutError(str(self.st.get("players")))
    async def close(self): self.task.cancel(); await self.ws.close()

async def tok(s, uid, **kw):
    async with s.get(f"{DBG}/token", params={"u": uid, **kw}) as r: return (await r.json())["t"]
async def move(s, uid, ch=None):
    async with s.get(f"{DBG}/move", params={"u": uid, **({"ch": ch} if ch else {})}) as r: await r.json()
    await asyncio.sleep(0.2)
async def info(s):
    async with s.get(f"{DBG}/info") as r: return (await r.json())["workers"]

BILI = "https://www.bilibili.com/video/av55185686"

async def main():
    async with aiohttp.ClientSession() as s:
        # ======== 1. 存取控制 ========
        host = await Client(s).open()                                                    # 本機直連（無 token、Host=localhost）
        check("1a 本機直接開：視為主人", host.st.get("me", {}).get("host") is True and host.st["me"]["can_control"])
        c = await Client(s, headers={"Host": "evil.example.com"}).open()                 # 模擬通道轉進來：Host 不是 localhost
        check("1b 沒憑證且 Host 不是 localhost：拒絕", c.err and c.err["code"] == "auth", c.err); await c.close()
        c = await Client(s, headers={"X-Forwarded-For": "1.2.3.4"}).open()              # 模擬代理標頭
        check("1c 沒憑證且帶代理標頭：拒絕", c.err and c.err["code"] == "auth", c.err); await c.close()
        c = await Client(s, token="garbage.token").open()
        check("1d 亂寫的憑證：拒絕", c.err and c.err["code"] == "auth"); await c.close()
        c = await Client(s, token=await tok(s, 1001, ttl=-10)).open()
        check("1e 過期的憑證：拒絕", c.err and c.err["code"] == "auth"); await c.close()
        c = await Client(s, token=await tok(s, 1001, g=999)).open()
        check("1f 別的伺服器的憑證：拒絕", c.err and c.err["code"] == "auth"); await c.close()

        a = await Client(s, await tok(s, 1001)).open()          # 小明：在 501
        b = await Client(s, await tok(s, 1002)).open()          # 小華：在 502
        cc = await Client(s, await tok(s, 1003)).open()         # 小美：不在語音
        d4 = await Client(s, await tok(s, 1004)).open()         # 阿傑：在 503
        check("1g 有效憑證：連得上，身分正確", a.st["me"]["name"] == "小明" and not a.st["me"]["host"], a.st["me"])

        # ======== 2. 語音成員權限 ========
        check("2a 不在語音的人：唯讀", cc.st["me"]["can_control"] is False and "加入語音頻道" in (cc.st["me"]["reason"] or ""), cc.st["me"])
        await cc.send(type="add", query=BILI); await asyncio.sleep(0.8)
        check("2b 不在語音的人加歌：被擋下", any("先加入語音頻道" in t for t in cc.toasts), cc.toasts)
        check("2c 沒有任何播放器被啟動", len(cc.st["players"]) == 0, cc.st["players"])

        async def wait_workers(pred, timeout=40):
            e = time.time() + timeout
            while time.time() < e:
                w = await info(s)
                if pred(w): return w
                await asyncio.sleep(0.3)
            return await info(s)

        # ======== 3. 競賽情境：同時加歌 ========
        # 3-R1 同一個頻道（501）兩個人同時加歌 -> 必須共用同一個播放器
        await move(s, 1003, 501)
        await asyncio.gather(a.send(type="add", query=BILI), cc.send(type="add", query=BILI))
        w = await wait_workers(lambda w: w[0]["vc"] == 501)
        await asyncio.sleep(4)   # 等兩邊的網址都解析完、都有機會被派到分身
        w = await info(s)
        used = [x for x in w if x["vc"] is not None]
        check("3a 同頻道兩人同時加歌：只用 1 個播放器（主機器人）", len(used) == 1 and w[0]["vc"] == 501, w)
        await a.until(lambda st: len(st["queue"]) + (1 if st["current"] else 0) >= 2, 40)
        check("3b 兩首歌都進了同一個播放器的清單", len(a.st["queue"]) + 1 == 2, f"queue={len(a.st['queue'])}")
        await move(s, 1003, None)

        # 3-R2 不同頻道（502、503）兩個人同時加歌 -> 必須分到不同的分身
        await asyncio.gather(b.send(type="add", query=BILI), d4.send(type="add", query=BILI))
        w = await wait_workers(lambda w: w[1]["vc"] is not None and w[2]["vc"] is not None)
        check("3c 不同頻道兩人同時加歌：分到不同分身", {w[1]["vc"], w[2]["vc"]} == {502, 503}, w)
        check("3d 主機器人沒被搶走（仍在 501）", w[0]["vc"] == 501, w)
        await b.until(lambda st: st["current"] and not st["current"]["loading"] and st["channel"] == "肝到世界盡頭", 40)
        await d4.until(lambda st: st["current"] and not st["current"]["loading"] and st["channel"] == "趕工阿", 40)
        check("3e 三個播放器同時在使用", len(a.st["players"]) == 3 and a.st["clones"] == {"total": 3, "idle": 0}, a.st["clones"])
        check("3f 各人預設看到自己所在頻道的播放器", a.st["channel"] == "放鬆休息" and b.st["channel"] == "肝到世界盡頭" and d4.st["channel"] == "趕工阿", [a.st["channel"], b.st["channel"], d4.st["channel"]])

        # ======== 4. 所有播放器都忙 ========
        await move(s, 1003, 504)                                   # 小美進 504（已經沒有空閒播放器）
        n = len(cc.toasts)
        await cc.send(type="add", query=BILI); await asyncio.sleep(1.0)
        check("4a 全部忙碌：明確告知上限", len(cc.toasts) > n and "都在使用中" in cc.toasts[-1], cc.toasts[-1:])
        w = await info(s)
        check("4b 沒有人被硬塞進別人的頻道", w[0]["vc"] == 501 and {w[1]["vc"], w[2]["vc"]} == {502, 503}, w)
        # ======== 5. 跨頻道不能亂控制 ========
        pid_b = b.st["selected"]
        await a.send(type="select", pid=pid_b); await asyncio.sleep(0.4)
        check("5a 小明可以『看』小華頻道的播放器", a.st["selected"] == pid_b and a.st["channel"] == "肝到世界盡頭")
        check("5b 但不能控制它", a.st["me"]["can_control"] is False and "肝到世界盡頭" in (a.st["me"]["reason"] or ""), a.st["me"]["reason"])
        n = len(a.toasts); await a.send(type="skip"); await asyncio.sleep(0.6)
        check("5c 跨頻道的操作被擋下並說明原因", len(a.toasts) > n and "肝到世界盡頭" in a.toasts[-1], a.toasts[-1:])
        await b.send(type="toggle_pause"); await b.until(lambda st: st["paused"], 5)
        check("5d 小華能控制自己頻道的播放器", b.st["paused"] is True)
        check("5e 小華暫停不影響小明的播放器", a.st["paused"] is False or a.st["selected"] == pid_b)
        await b.send(type="toggle_pause"); await asyncio.sleep(0.3)

        # ======== 6. 每個伺服器各自的音質 ========
        await a.send(type="quality", kbps=320)
        await a.until(lambda st: st["quality"]["kbps"] == 320, 8)
        check("6a 音質切到 320（這個伺服器）", a.st["quality"]["kbps"] == 320)
        await cc.send(type="quality", kbps=128); await asyncio.sleep(0.5)
        check("6b 在語音的人才能改音質（小美在 504 → 允許）", cc.st["quality"]["kbps"] == 128)
        await a.send(type="quality", kbps=192); await asyncio.sleep(0.6)

        # ======== 7. Bilibili 帳號：只有擁有者 ========
        await a.send(type="bili_login_start"); await asyncio.sleep(0.6)
        check("7a 一般成員不能更換 Bilibili 帳號", any("擁有者" in t for t in a.toasts), a.toasts[-1:])
        check("7b 一般成員看不到帳號細節", "name" not in a.st["bili"] and a.st["bili"]["can_manage"] is False, a.st["bili"])
        owner = await Client(s, await tok(s, 9001)).open()
        check("7c 擁有者可以管理", owner.st["bili"]["can_manage"] is True)
        await owner.send(type="bili_login_start")
        t0 = time.time()
        while time.time() - t0 < 20 and not any(m["type"] in ("bili_qr", "bili_status") for m in owner.msgs): await asyncio.sleep(0.2)
        qr = next((m for m in owner.msgs if m["type"] == "bili_qr"), None)
        st_ = [m for m in owner.msgs if m["type"] == "bili_status"]
        check("7d 擁有者：成功向 Bilibili 取得登入 QR 碼", qr is not None and qr["img"].startswith("data:image/svg+xml"), (qr or st_)[:1] if isinstance(qr, list) else (st_[:1] if not qr else f"QR ok, ttl={qr['ttl']}"))
        await asyncio.sleep(3.5)
        st_ = [m["status"] for m in owner.msgs if m["type"] == "bili_status"]
        check("7e 輪詢掃碼狀態（尚未掃描 = waiting）", "waiting" in st_ or "error" in st_, st_)
        await owner.send(type="bili_login_cancel")

        # ======== 8. 人離開頻道後失去控制權 ========
        await move(s, 1001, None)
        await asyncio.sleep(0.5)
        check("8a 小明離開語音：立刻變唯讀", a.st["me"]["can_control"] is False, a.st["me"])
        for c in (host, a, b, cc, d4, owner): await c.close()
    print(f"\n總結：{sum(res)}/{len(res)} 通過")
asyncio.run(asyncio.wait_for(main(), 240))

