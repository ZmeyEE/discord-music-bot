"""中繼站 + 驗證模式：專屬連結與裝置憑證經過中繼站也能正常運作
Relay + verify mode: personal links and device tokens also work through the relay

用 tests/run_all.py 或 tests/run_relay.py 執行 / run it with tests/run_all.py or tests/run_relay.py
"""
import asyncio, aiohttp, json, re, time
RELAY = "ws://127.0.0.1:8770"; DBG = "http://127.0.0.1:8767"; GID = 777
res = []
def check(n, ok, d=""): res.append(bool(ok)); print(("PASS" if ok else "FAIL"), n, str(d)[:150], flush=True)
async def conn(s, q=""):
    ws = await s.ws_connect(f"{RELAY}/ws/{GID}{q}")
    box = {"st": None, "vtoken": None, "types": []}
    async def pump():
        async for m in ws:
            if m.type != aiohttp.WSMsgType.TEXT: continue
            d = json.loads(m.data); box["types"].append(d["type"])
            if d["type"] == "state": box["st"] = d["data"]
            elif d["type"] == "verified": box["vtoken"] = d["token"]
    asyncio.create_task(pump()); await asyncio.sleep(1.2); return ws, box
async def dbg(s, path, **p):
    async with s.get(f"{DBG}/{path}", params=p) as r: return await r.json()
async def main():
    async with aiohttp.ClientSession() as s:
        ws, b = await conn(s)
        check("V1 經中繼站、沒有連結：未驗證，且不再收到驗證碼", b["st"]["me"]["pending"] and "verify" not in b["types"], b["types"])
        tok = (await dbg(s, "token", u=1001))["t"]
        ws1, b1 = await conn(s, f"?t={tok}")
        check("V2 經中繼站點專屬連結：直接驗證，真實暱稱", b1["st"]["me"]["name"] == "小明" and not b1["st"]["me"]["pending"], b1["st"]["me"])
        check("V3 並且拿到裝置憑證（之後免連結）", b1["vtoken"] and len(b1["vtoken"]) >= 40)
        ws2, b2 = await conn(s, f"?d={b1['vtoken']}")
        check("V4 經中繼站、帶裝置憑證重新連線：免連結，真實暱稱", b2["st"]["me"]["name"] == "小明" and not b2["st"]["me"]["pending"], b2["st"]["me"])
        async with s.get("http://127.0.0.1:8770/api/guilds") as resp:
            check("V5 驗證模式：中繼站的 /api/guilds 不公開", resp.status == 403, resp.status)
    print(f"總結：{sum(res)}/{len(res)} 通過")
asyncio.run(asyncio.wait_for(main(), 60))
