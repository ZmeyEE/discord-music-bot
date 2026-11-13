"""驗證模式（verify）：專屬連結、裝置憑證、撤銷、退出伺服器、重啟後仍記得
Verify mode: personal links, device tokens, revoke, leaving the server, remembered after a restart

用 tests/run_all.py 或 tests/run_relay.py 執行 / run it with tests/run_all.py or tests/run_relay.py
"""
import asyncio, aiohttp, json, os, re, time
BASE = "http://127.0.0.1:8766"; DBG = "http://127.0.0.1:8767"; GID = 777
res = []
def check(n, ok, d=""): res.append(bool(ok)); print(("PASS" if ok else "FAIL"), n, str(d)[:170], flush=True)
REMOTE = {"Host": "friend.example.com", "X-Forwarded-For": "203.0.113.7"}   # 模擬從外面（中繼站／通道）進來

class Client:
    def __init__(self, s, token=None, device=None, name=None, base=BASE):
        self.s, self.token, self.device, self.name, self.base = s, token, device, name, base
        self.st = {}; self.toasts = []; self.msgs = []; self.err = None; self.vtoken = None; self.vname = None; self.revoked = False
    async def open(self):
        q = [x for x in (f"t={self.token}" if self.token else "", f"d={self.device}" if self.device else "", f"n={self.name}" if self.name else "") if x]
        self.ws = await self.s.ws_connect(f"{self.base.replace('http','ws')}/ws/{GID}" + ("?" + "&".join(q) if q else ""), headers=REMOTE)
        self.task = asyncio.create_task(self._pump()); await asyncio.sleep(0.7); return self
    async def _pump(self):
        async for m in self.ws:
            if m.type != aiohttp.WSMsgType.TEXT: continue
            d = json.loads(m.data); self.msgs.append(d); t = d["type"]
            if t == "state": self.st = d["data"]
            elif t == "toast": self.toasts.append(d["text"])
            elif t == "error": self.err = d
            elif t == "verified": self.vtoken, self.vname = d["token"], d["name"]
            elif t == "revoked": self.revoked = True
    async def send(self, **o): await self.ws.send_str(json.dumps(o))
    async def until(self, pred, t=40):
        e = time.time() + t
        while time.time() < e:
            if pred(): return True
            await asyncio.sleep(0.15)
        return False
    async def close(self): self.task.cancel(); await self.ws.close()

async def dbg(s, path, **p):
    async with s.get(f"{DBG}/{path}", params=p) as r: return await r.json()
BILI = "https://www.bilibili.com/video/av55185686"

async def main():
    async with aiohttp.ClientSession() as s:
        # ===== 1. 沒有連結：什麼都看不到、什麼都不能做 =====
        a = await Client(s, name="路人").open()
        check("1a 沒有連結：狀態是 pending，且沒有洩漏播放資訊", a.st["me"]["pending"] is True and "players" not in a.st and "queue" not in a.st, list(a.st))
        check("1b 不再發驗證碼（已改成點連結）", not any(m["type"] == "verify" for m in a.msgs), [m["type"] for m in a.msgs])
        n = len(a.toasts); await a.send(type="add", query=BILI); await asyncio.sleep(0.6)
        check("1c 未驗證：加歌被擋下，並告訴他用 /help 連結", len(a.toasts) > n and "/help" in a.toasts[-1], a.toasts[-1:])
        async with s.get("http://127.0.0.1:8766/api/guilds", headers=REMOTE) as r:
            check("1d 驗證模式：/api/guilds 不對外公開", r.status == 403, r.status)
        await a.send(type="verify_refresh"); await asyncio.sleep(0.4)
        check("1e 舊的 verify_refresh 訊息不再有任何作用", not any(m["type"] == "verify" for m in a.msgs))

        # ===== 2. 點 /help 的專屬連結：零輸入，自動綁定 =====
        t1 = (await dbg(s, "token", u=1001))["t"]
        a2 = await Client(s, token=t1).open()
        check("2a 點連結：直接驗證，名字是真實暱稱，可控制", a2.st["me"]["name"] == "小明" and not a2.st["me"]["pending"] and a2.st["me"]["can_control"], a2.st["me"])
        await a2.until(lambda: a2.vtoken)
        check("2b 並且自動替這個瀏覽器登記成記住的裝置（拿到長憑證）", a2.vtoken and len(a2.vtoken) >= 40 and a2.vname == "小明", (a2.vname, len(a2.vtoken or "")))
        check("2c 驗證模式：不需要在語音頻道也能控制所有頻道", a2.st["me"]["can_control"] is True)
        tamper = t1[:-3] + ("AAA" if not t1.endswith("AAA") else "BBB")
        f1 = await Client(s, token=tamper).open()
        check("2d 竄改過的連結：當作沒驗證，進不去", f1.st["me"]["pending"] is True and f1.vtoken is None, f1.st["me"]); await f1.close()
        tg = (await dbg(s, "token", u=1001, g=999))["t"]
        f2 = await Client(s, token=tg).open()
        check("2e 別的伺服器簽出的連結：不能用在這個伺服器", f2.st["me"]["pending"] is True, f2.st["me"]); await f2.close()
        ttl = (await dbg(s, "token", u=1001, ttl=-5))["t"]
        f3 = await Client(s, token=ttl).open()
        check("2f 過期的連結：進不去", f3.st["me"]["pending"] is True, f3.st["me"]); await f3.close()

        # ===== 3. 記住的裝置：重新開啟不用再點連結（存在主機）=====
        b = await Client(s, device=a2.vtoken).open()
        check("3a 只帶裝置憑證重新連線：直接是已驗證，真實暱稱", b.st["me"]["name"] == "小明" and not b.st["me"]["pending"], b.st["me"])
        f = await Client(s, device="not-a-real-device-token").open()
        check("3b 亂寫的裝置憑證：當作未驗證", f.st["me"]["pending"] is True, f.st["me"]); await f.close()
        raw = (await dbg(s, "registry_file"))["raw"]
        check("3c members.json 只存雜湊，不存憑證本身", a2.vtoken not in raw and "小明" in raw, f"含明文憑證: {a2.vtoken in raw}")
        n_before = (await dbg(s, "restart_registry"))["devices"]
        c = await Client(s, device=a2.vtoken).open()
        check("3d 模擬機器人重啟後：記住的裝置仍然有效", n_before >= 1 and c.st["me"]["name"] == "小明", n_before)

        # ===== 4. 換新裝置：再點一次 /help 連結就好 =====
        tok = (await dbg(s, "token", u=1002))["t"]
        d = await Client(s, token=tok).open()
        check("4a 另一個人點連結：名字是他的真實暱稱", d.st["me"]["name"] == "小華" and not d.st["me"]["pending"], d.st["me"])
        await d.until(lambda: d.vtoken)
        e = await Client(s, device=d.vtoken).open()
        check("4b 之後只靠裝置憑證就能進來（連結過期也沒關係）", e.st["me"]["name"] == "小華", e.st["me"])

        # ===== 5. 已經不在伺服器的人 =====
        ex = (await dbg(s, "regdevice", u=4040))["d"]
        x = await Client(s, device=ex).open()
        check("5a 已退出伺服器的人：裝置憑證失效，回到未驗證", x.st["me"]["pending"] is True, x.st["me"])
        x2 = await Client(s, device=ex).open()
        check("5b 並且已被主機撤銷（再用也一樣進不來）", x2.st["me"]["pending"] is True)
        await x.close(); await x2.close()

        # ===== 6. 擁有者與底線 =====
        otok = (await dbg(s, "token", u=9001))["t"]
        o = await Client(s, token=otok).open()
        check("6a 擁有者用 /help 連結：有 Bilibili 管理入口", o.st["bili"]["can_manage"] is True and o.st["me"]["owner"] is True)
        check("6b 一般驗證成員：沒有 Bilibili 管理入口", b.st["bili"]["can_manage"] is False)
        n = len(b.toasts); await b.send(type="bili_login_start"); await asyncio.sleep(0.6)
        check("6c 一般驗證成員不能發起 Bilibili 登入", len(b.toasts) > n and "擁有者" in b.toasts[-1], b.toasts[-1:])

        # ===== 7. 已驗證的人真的能操作，而且點歌者是真實暱稱 =====
        await b.send(type="add", query=BILI, channel="502")
        ok_play = await b.until(lambda: b.st.get("current") and not b.st["current"]["loading"], 60)
        check("7a 已驗證的人可以指定任一頻道加歌並播放", ok_play and b.st["channel"] == "肝到世界盡頭", b.st.get("channel"))
        check("7b 『點歌者』顯示真實 Discord 暱稱，不是訪客", b.st["current"]["requester"] == "小明", b.st["current"]["requester"])

        # ===== 8. 撤銷（/unverify）=====
        res_ = await dbg(s, "revoke", u=1001)
        await b.until(lambda: b.revoked)
        check("8a 撤銷後：正在連線的瀏覽器立刻被降回未驗證", res_["n"] >= 1 and b.revoked and b.st["me"]["pending"] is True, (res_, b.st["me"]))
        g2 = await Client(s, device=a2.vtoken).open()
        check("8b 被撤銷的裝置憑證再也不能用", g2.st["me"]["pending"] is True)
        h = await Client(s, device=e.device).open()
        check("8c 撤銷一個人不影響別人（小華仍然有效）", h.st["me"]["name"] == "小華", h.st["me"])
        for c_ in (a, a2, b, c, d, e, g2, h, o): await c_.close()
    print(f"\n總結：{sum(res)}/{len(res)} 通過")
asyncio.run(asyncio.wait_for(main(), 300))
