"""中繼站加固測試：路徑穿越、限流、握手封鎖（獨立啟動 Relay，不需要家裡的機器人）
Relay hardening tests: path traversal, rate limits, handshake lock-out (starts a Relay on its own, no bot at home needed)

用 tests/run_all.py 或 tests/run_relay.py 執行 / run it with tests/run_all.py or tests/run_relay.py
"""
import os
import asyncio, hashlib, hmac, json, sys
import aiohttp
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 專案根目錄 / project root
sys.path.insert(0, ROOT)
from musicbot import relay as R

PORT = 8791
BASE = f"http://127.0.0.1:{PORT}"
KEY = "k" * 32
res = []
def check(n, ok, d=""): res.append(bool(ok)); print(("PASS" if ok else "FAIL"), n, str(d)[:200], flush=True)

def xff(ip): return {"X-Forwarded-For": ip}

async def bad_worker(s, ip):
    ws = await s.ws_connect(f"{BASE}/relay", headers=xff(ip))
    ch = await ws.receive_json()
    await ws.send_json({"t": "auth", "proof": "0" * 64})
    m = await ws.receive()
    await ws.close()
    return m

async def main():
    rl = R.Relay(KEY, "127.0.0.1", PORT)
    await rl.start()
    R.AUTH_LOCKOUT = 3.0   # 縮短封鎖時間方便測試
    async with aiohttp.ClientSession() as s:
        # 1. 安全標頭
        for path in ("/", "/static/app.js", "/healthz", "/api/guilds", "/nope"):
            async with s.get(BASE + path) as r:
                h = r.headers
                ok = ("frame-ancestors 'none'" in h.get("Content-Security-Policy", "") and h.get("X-Content-Type-Options") == "nosniff"
                      and h.get("X-Frame-Options") == "DENY" and h.get("Cache-Control") == "no-store" and h.get("Referrer-Policy") == "no-referrer")
                check(f"1 安全標頭 {path} ({r.status})", ok, dict(h) if not ok else "")
        # 路徑穿越
        async with s.get(BASE + "/static/../.env") as r: check("1x 路徑穿越被擋", r.status in (403, 404), r.status)
        async with s.get(BASE + "/static/%2e%2e/musicbot/relay.py") as r: check("1y 編碼路徑穿越被擋", r.status in (403, 404), r.status)

        # 2. 單一 IP 同時連線上限（瀏覽器端）
        socks = []
        for i in range(R.MAX_PER_IP):
            socks.append(await s.ws_connect(f"{BASE}/ws/1", headers=xff("9.9.9.9")))
        try:
            await s.ws_connect(f"{BASE}/ws/1", headers=xff("9.9.9.9"))
            check("2a 同一 IP 超過同時上限被擋", False)
        except aiohttp.WSServerHandshakeError as e:
            check("2a 同一 IP 超過同時上限被擋 (429)", e.status == 429, e.status)
        w = await s.ws_connect(f"{BASE}/ws/1", headers=xff("8.8.8.8"))
        check("2b 別的 IP 不受影響", not w.closed)
        await w.close()
        for x in socks: await x.close()
        await asyncio.sleep(0.5)
        w = await s.ws_connect(f"{BASE}/ws/1", headers=xff("9.9.9.9"))
        check("2c 關閉舊連線後名額釋放", not w.closed)
        await w.close()
        check("2d 計數歸零不洩漏", "9.9.9.9" not in rl._per_ip, rl._per_ip)

        # 3. 每分鐘新連線上限
        got429 = 0
        for i in range(R.NEW_PER_MINUTE + 10):
            try:
                x = await s.ws_connect(f"{BASE}/ws/1", headers=xff("7.7.7.7")); await x.close()
            except aiohttp.WSServerHandshakeError as e:
                if e.status == 429: got429 += 1
        check("3 每分鐘新連線超過上限被 429", got429 >= 8, got429)

        # 4. 直接連線不能用標頭偽造 IP？（本機 peer 是 loopback，所以標頭被信任——這是預期；
        #    真正的防偽造由『非 loopback 對端忽略標頭』保證，用單元方式驗證）
        class FakeReq:
            def __init__(self, remote, headers): self.remote, self.headers = remote, headers
        check("4a loopback 對端：信任 X-Forwarded-For", R.client_ip(FakeReq("127.0.0.1", {"X-Forwarded-For": "1.2.3.4, 5.6.7.8"})) == "1.2.3.4")
        check("4b 外部對端：忽略偽造的標頭", R.client_ip(FakeReq("45.1.1.1", {"X-Forwarded-For": "1.2.3.4", "CF-Connecting-IP": "2.2.2.2"})) == "45.1.1.1")
        check("4c CF-Connecting-IP 優先", R.client_ip(FakeReq("::1", {"CF-Connecting-IP": "3.3.3.3", "X-Forwarded-For": "1.1.1.1"})) == "3.3.3.3")

        # 5. 握手失敗封鎖
        ip = "6.6.6.6"
        for i in range(R.AUTH_FAIL_LIMIT):
            await bad_worker(s, ip)
        try:
            await s.ws_connect(f"{BASE}/relay", headers=xff(ip))
            check("5a 連續失敗後被封鎖", False)
        except aiohttp.WSServerHandshakeError as e:
            check("5a 連續失敗後被封鎖 (429)", e.status == 429, e.status)
        # 另一個 IP 用正確金鑰仍可連
        ws = await s.ws_connect(f"{BASE}/relay", headers=xff("5.5.5.5"))
        ch = await ws.receive_json()
        await ws.send_json({"t": "auth", "proof": R.proof(KEY, ch["nonce"])})
        m = await asyncio.wait_for(ws.receive(), 5)
        ok = m.type == aiohttp.WSMsgType.TEXT and json.loads(m.data).get("t") == "ready"
        check("5b 其他 IP 用正確金鑰不受影響", ok, m.data if m.type == aiohttp.WSMsgType.TEXT else m.type)
        await ws.close()
        await asyncio.sleep(3.3)
        try:
            ws = await s.ws_connect(f"{BASE}/relay", headers=xff(ip))
            check("5c 封鎖到期後恢復", True); await ws.close()
        except aiohttp.WSServerHandshakeError as e:
            check("5c 封鎖到期後恢復", False, e.status)

        # 6. 同時握手上限（不回應的連線佔位）
        ip = "4.4.4.4"
        holders = []
        for i in range(R.MAX_HANDSHAKES_PER_IP):
            x = await s.ws_connect(f"{BASE}/relay", headers=xff(ip)); await x.receive_json(); holders.append(x)
        try:
            await s.ws_connect(f"{BASE}/relay", headers=xff(ip))
            check("6a 同時握手上限", False)
        except aiohttp.WSServerHandshakeError as e:
            check("6a 同時握手上限 (429)", e.status == 429, e.status)
        for x in holders: await x.close()
        await asyncio.sleep(0.5)
        check("6b 握手計數釋放", ip not in rl._handshakes, rl._handshakes)

        # 7. 瀏覽器訊息大小上限
        x = await s.ws_connect(f"{BASE}/ws/1", headers=xff("3.3.3.3"))
        await x.send_str("x" * (R.MAX_MSG_BYTES + 10))
        m = None
        for _ in range(5):                       # 先讀掉伺服器送的"離線"通知
            m = await asyncio.wait_for(x.receive(), 5)
            if m.type != aiohttp.WSMsgType.TEXT: break
        check("7 超大訊息：連線被關閉", m.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR), m.type)

        # 8. 垃圾輸入不會讓伺服器崩潰
        for bad in ("{", "[]", "null", '{"type":123}', '{"type":"add","query":' + '"a"' * 3 + '}'):
            y = await s.ws_connect(f"{BASE}/ws/1", headers=xff("2.2.2.2"))
            await y.send_str(bad); await asyncio.sleep(0.1); await y.close()
        async with s.get(f"{BASE}/healthz") as r: check("8 垃圾輸入後仍然健康", r.status == 200)
    await rl.stop()
    print(f"\n總結：{sum(res)}/{len(res)} 通過")

asyncio.run(asyncio.wait_for(main(), 120))
