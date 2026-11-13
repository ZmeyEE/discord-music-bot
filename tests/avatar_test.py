"""點歌者頭像：Discord 成員有頭像網址，本地／訪客沒有
Requester avatars: Discord members get an avatar URL, local / guest users do not

用 tests/run_all.py 或 tests/run_relay.py 執行 / run it with tests/run_all.py or tests/run_relay.py
"""
import asyncio, aiohttp, json, time
BASE = "http://127.0.0.1:8766"; DBG = "http://127.0.0.1:8767"; GID = 777
res = []
def check(n, ok, d=""): res.append(bool(ok)); print(("PASS" if ok else "FAIL"), n, str(d)[:200], flush=True)
REMOTE = {"Host": "friend.example.com", "X-Forwarded-For": "203.0.113.7"}
BILI = "https://www.bilibili.com/video/av55185686"
class C:
    def __init__(self, s, token=None, remote=True): self.s, self.token, self.remote, self.st = s, token, remote, {}
    async def open(self):
        q = f"?t={self.token}" if self.token else ""
        self.ws = await self.s.ws_connect(f"{BASE.replace('http','ws')}/ws/{GID}{q}", headers=REMOTE if self.remote else None)
        self.task = asyncio.create_task(self._pump()); await asyncio.sleep(0.7); return self
    async def _pump(self):
        async for m in self.ws:
            if m.type == aiohttp.WSMsgType.TEXT:
                d = json.loads(m.data)
                if d["type"] == "state": self.st = d["data"]
    async def send(self, **o): await self.ws.send_str(json.dumps(o))
    async def until(self, p, t=60):
        e = time.time() + t
        while time.time() < e:
            if p(): return True
            await asyncio.sleep(0.15)
        return False
async def tok(s, uid):
    async with s.get(f"{DBG}/token", params={"u": uid}) as r: return (await r.json())["t"]
async def main():
    async with aiohttp.ClientSession() as s:
        a = await C(s, await tok(s, 1001)).open()                       # 小明（Discord 成員）
        await a.send(type="add", query=BILI, channel="501")
        ok = await a.until(lambda: a.st.get("current") and not a.st["current"]["loading"])
        cur = a.st.get("current") or {}
        check("A1 Discord 成員點歌：目前播放帶有他的頭像網址（https、64px）", ok and cur.get("requester") == "小明" and cur.get("requester_avatar", "").startswith("https://cdn.discordapp.com/avatars/1001/") and "size=64" in cur["requester_avatar"], cur.get("requester_avatar"))
        await a.send(type="add", query=BILI, channel="501", when="end")
        await a.until(lambda: a.st.get("queue"))
        q0 = (a.st.get("queue") or [{}])[0]
        check("A2 待播卡片也帶頭像", q0.get("requester_avatar", "").startswith("https://cdn.discordapp.com/avatars/1001/"), q0.get("requester_avatar"))
        b = await C(s, await tok(s, 1002)).open()                       # 小華：同一首歌（走快取）不能沿用小明的頭像
        await b.send(type="add", query=BILI, channel="502")
        await b.until(lambda: any(p["name"] == "肝到世界盡頭" for p in b.st.get("players", [])))
        await b.send(type="select", pid=next(p["pid"] for p in b.st["players"] if p["name"] == "肝到世界盡頭"))
        await b.until(lambda: b.st.get("channel") == "肝到世界盡頭" and b.st.get("current") and not b.st["current"]["loading"])
        cb = b.st.get("current") or {}
        check("A3 另一個人點同一首（快取命中）：頭像是他自己的，不會沿用上一位", cb.get("requester") == "小華" and "/avatars/1002/" in cb.get("requester_avatar", ""), cb.get("requester_avatar"))
        h = await C(s, None, remote=False).open()                       # 本機（沒有 Discord 身分）
        await h.send(type="add", query=BILI, channel="503")
        await h.until(lambda: any(p["name"] == "趕工阿" for p in h.st.get("players", [])))
        await h.send(type="select", pid=next(p["pid"] for p in h.st["players"] if p["name"] == "趕工阿"))
        await h.until(lambda: h.st.get("channel") == "趕工阿" and h.st.get("current") and not h.st["current"]["loading"])
        ch = h.st.get("current") or {}
        check("A4 本機／訪客沒有 Discord 身分：頭像為空（前端改用暱稱首字）", ch.get("requester") and ch.get("requester_avatar") == "", (ch.get("requester"), ch.get("requester_avatar")))
        for x in (a, b, h): await x.ws.close()
    print(f"總結：{sum(res)}/{len(res)} 通過")
asyncio.run(asyncio.wait_for(main(), 200))
