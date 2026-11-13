"""中繼站補充測試：播放端離線與自動恢復、語音模式經過中繼站
Extra relay tests: player side offline and auto-recovery, voice mode through the relay

用 tests/run_all.py 或 tests/run_relay.py 執行 / run it with tests/run_all.py or tests/run_relay.py
"""
import asyncio, aiohttp, json, os, subprocess, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # project root / 專案根目錄
RELAY = "ws://127.0.0.1:8770"; GID = 777
res = []
def check(n, ok, d=""): res.append(bool(ok)); print(("PASS" if ok else "FAIL"), n, str(d)[:150], flush=True)
async def conn(s, q=""):
    ws = await s.ws_connect(f"{RELAY}/ws/{GID}{q}")
    box = {"st": None, "err": None, "closed": False}
    async def pump():
        async for m in ws:
            if m.type == aiohttp.WSMsgType.TEXT:
                d = json.loads(m.data)
                if d["type"] == "state": box["st"] = d["data"]; box["err"] = None
                elif d["type"] == "error": box["err"] = d
        box["closed"] = True
    asyncio.create_task(pump()); return ws, box
async def main():
    mode = sys.argv[1]
    async with aiohttp.ClientSession() as s:
        if mode == "recover":
            ws, b = await conn(s, "?n=阿花")
            await asyncio.sleep(1.0)
            check("R1 播放端離線時：瀏覽器先收到離線通知", b["err"] and b["err"]["code"] == "offline", b["err"])
            print("   …現在啟動播放端，等待自動重連…", flush=True)
            subprocess.Popen([sys.executable, "-X", "utf8", os.environ["HARNESS"]], cwd=ROOT,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            t0 = time.time()
            while time.time() - t0 < 45 and not b["st"]: await asyncio.sleep(0.3)
            check("R2 播放端回來後：同一個瀏覽器自動收到狀態（沒有重新整理）", b["st"] and b["st"]["guild"]["name"] == "測試伺服器", f"{time.time()-t0:.1f}s")
            check("R3 離線提示已消失", b["err"] is None and not b["closed"])
        else:  # voice
            ws, b = await conn(s)
            await asyncio.sleep(1.0)
            check("V1 語音模式：沒有憑證，經中繼站（即使連自 loopback）也進不來", b["err"] and b["err"]["code"] == "auth", b["err"])
            async with s.get("http://127.0.0.1:8770/api/guilds") as r:
                check("V2 語音模式：/api/guilds 不對外公開", r.status == 403, r.status)
            async with s.get("http://127.0.0.1:8767/token", params={"u": 1001}) as r: t = (await r.json())["t"]
            ws2, b2 = await conn(s, f"?t={t}")
            await asyncio.sleep(1.0)
            check("V3 語音模式：帶有效憑證經中繼站可以進來，身分是憑證上的人", b2["st"] and b2["st"]["me"]["name"] == "小明", b2["st"] and b2["st"]["me"])
    print(f"總結：{sum(res)}/{len(res)} 通過")
asyncio.run(asyncio.wait_for(main(), 120))
