"""大清單測試（真的看板 + WebSocket，待播 5000 首）：只送一頁、沒變不重送、往下要更多、改了才重送
Large-queue test (the real dashboard + WebSocket, 5000 queued songs): one page only, no re-send when unchanged, more on request, re-sent after a change

由 tests/run_all.py 啟動 harness 後執行 / run by tests/run_all.py after it starts the harness
"""
import asyncio
import json
import sys

import aiohttp

res = []
def check(n, ok, d=""): res.append(bool(ok)); print(("PASS" if ok else "FAIL"), n, str(d)[:190], flush=True)

WS, DBG, N = "ws://127.0.0.1:8766/ws/777?n=", "http://127.0.0.1:8767", 5000


async def take(ws, seconds=1.2):
    """收這段時間內的所有狀態訊息，回傳 [(位元組數, data)] / Collect every state message for a while: [(bytes, data)]."""
    out = []
    try:
        while True:
            m = await asyncio.wait_for(ws.receive(), seconds)
            if m.type != aiohttp.WSMsgType.TEXT:
                break
            d = json.loads(m.data)
            if d["type"] == "state":
                out.append((len(m.data), d["data"]))
    except asyncio.TimeoutError:
        pass
    return out


async def main():
    async with aiohttp.ClientSession() as s:
        async def dbg(path):
            async with s.get(DBG + path) as r:
                return await r.json()
        check("F1 塞進 5000 首", (await dbg(f"/fill?n={N}"))["queue"] == N)

        # ---- 舊版網頁：不送 queue_window ----
        async with s.ws_connect(WS + "old", max_msg_size=0) as old:
            first = (await take(old))[-1]
            check("O1 一連上只收到一頁（100 首），總數 5000", len(first[1]["queue"]) == 100 and first[1]["queue_total"] == N, (len(first[1]["queue"]), first[1]["queue_total"]))
            check("O2 第一份狀態小於 60 KB（原本 1000 首是 287 KB）", first[0] < 60_000, first[0])
            check("O3 快照帶著一頁和上限的大小，指紋不外流", first[1]["queue_window"] == {"page": 100, "max": 1000} and "queue_sig" not in first[1], first[1].get("queue_window"))
            await dbg("/poke?n=5&gap=0.08")
            got = await take(old)
            check("O4 舊版網頁每次都還是拿得到清單（不會壞）", got and all("queue" in d for _, d in got), len(got))

        # ---- 新版網頁：一連上就送 queue_window ----
        async with s.ws_connect(WS + "new", max_msg_size=0) as new:
            await take(new, 0.8)
            await new.send_str(json.dumps({"type": "queue_window"}))
            await take(new, 0.8)
            await dbg("/poke?n=20&gap=0.06")
            got = await take(new)
            total = sum(b for b, _ in got)
            check("W1 20 次通知：一次都沒重送清單", got and not any("queue" in d for _, d in got), (len(got), sum("queue" in d for _, d in got)))
            check("W2 20 次通知總共不到 60 KB（原本 5.7 MB）", total < 60_000, total)
            check("W3 沒帶清單的狀態還是有總數", all(d["queue_total"] == N for _, d in got))

            await new.send_str(json.dumps({"type": "queue_window", "limit": 300}))
            got = await take(new, 0.8)
            check("W4 往下要 300 首：回一份 300 首的清單", got and len(got[-1][1].get("queue", [])) == 300, [len(d.get("queue", [])) for _, d in got])
            await new.send_str(json.dumps({"type": "queue_window", "limit": 10 ** 6}))
            got = await take(new, 0.8)
            check("W5 要超過上限：只給 1000 首", got and len(got[-1][1].get("queue", [])) == 1000, [len(d.get("queue", [])) for _, d in got])
            await new.send_str(json.dumps({"type": "queue_window", "limit": 100}))
            page = (await take(new, 0.8))[-1][1]["queue"]

            # 改視窗裡的東西：要重送 / a change inside the window: re-sent
            await new.send_str(json.dumps({"type": "remove", "id": page[0]["id"]}))
            got = await take(new)
            with_q = [d for _, d in got if "queue" in d]
            check("W6 刪掉第一首：清單重送，原本第二首變第一首，總數少 1",
                  with_q and with_q[-1]["queue"][0]["id"] == page[1]["id"] and with_q[-1]["queue_total"] == N - 1,
                  (len(with_q), with_q[-1]["queue_total"] if with_q else None))
            await new.send_str(json.dumps({"type": "move", "id": page[5]["id"], "index": 0}))
            got = await take(new)
            with_q = [d for _, d in got if "queue" in d]
            check("W7 把第六首拖到最前面：清單重送且順序正確", with_q and with_q[-1]["queue"][0]["id"] == page[5]["id"])
            await dbg("/poke?n=5&gap=0.08")
            got = await take(new)
            check("W8 之後沒變，又不重送了", got and not any("queue" in d for _, d in got))

        # ---- 兩個瀏覽器視窗大小不同，互不影響 ----
        async with s.ws_connect(WS + "a", max_msg_size=0) as a, s.ws_connect(WS + "b", max_msg_size=0) as b:
            await take(a, 0.6); await take(b, 0.6)
            await a.send_str(json.dumps({"type": "queue_window", "limit": 400}))
            await b.send_str(json.dumps({"type": "queue_window"}))
            ga, gb = await take(a, 0.8), await take(b, 0.8)
            await a.send_str(json.dumps({"type": "shuffle"}))
            ga, gb = await take(a), await take(b)
            la = [len(d["queue"]) for _, d in ga if "queue" in d]
            lb = [len(d["queue"]) for _, d in gb if "queue" in d]
            check("M1 隨機打亂後：甲收到 400 首、乙收到 100 首", la[-1:] == [400] and lb[-1:] == [100], (la, lb))


asyncio.run(asyncio.wait_for(main(), 120))
print(f"{sum(res)}/{len(res)} 通過", flush=True)
sys.exit(0 if all(res) else 1)
