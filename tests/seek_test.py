"""跳轉：拖曳進度條、暫停中跳轉要維持暫停
Seeking: dragging the progress bar, staying paused when seeking while paused

用 tests/run_all.py 或 tests/run_relay.py 執行 / run it with tests/run_all.py or tests/run_relay.py
"""
import asyncio, aiohttp, json, time
res = []
def check(n, ok, d=""): res.append(ok); print(("PASS" if ok else "FAIL"), n, d, flush=True)
async def main():
    async with aiohttp.ClientSession() as s, s.ws_connect("http://127.0.0.1:8766/ws/777") as ws:
        st = {}
        async def pump():
            async for m in ws:
                d = json.loads(m.data)
                if d["type"] == "state": st["d"] = d["data"]
        task = asyncio.create_task(pump()); send = lambda o: ws.send_str(json.dumps(o))
        async def until(p, t=20):
            e = time.time() + t
            while time.time() < e:
                if st.get("d") and p(st["d"]): return st["d"]
                await asyncio.sleep(0.1)
            raise TimeoutError()
        await asyncio.sleep(0.5)
        await send({"type": "stop"}); await asyncio.sleep(0.6)
        await send({"type": "add", "query": "https://www.bilibili.com/video/av55185686"})
        await until(lambda d: d['current'] and not d['current']['loading'] and d['current']['duration'], 40)
        await send({"type": "add", "query": "yt: lofi hip hop beats"})
        d = await until(lambda d: d["current"] and not d["current"]["loading"] and len(d["queue"]) == 1 and d["queue"][0]["thumbnail"], 40)
        cid, q0 = d["current"]["id"], [t["id"] for t in d["queue"]]
        dur = d["current"]["duration"]
        # 1. 播放中跳轉
        await send({"type": "seek", "position": 100})
        d = await until(lambda d: d["current"] and d["current"]["position"] >= 99, 10)
        check("1 播放中跳到 100 秒", 99 <= d["current"]["position"] < 104, f"pos={d['current']['position']}")
        check("1 仍是同一首、佇列不變", d["current"]["id"] == cid and [t["id"] for t in d["queue"]] == q0)
        # 2. 位置持續往前走
        await asyncio.sleep(2); await send({"type": "loop", "mode": "off"}); await asyncio.sleep(0.4)
        check("2 跳轉後進度持續前進", st["d"]["current"]["position"] >= 100.5, f"pos={st['d']['current']['position']}")
        # 3. 暫停中跳轉 -> 會繼續播（位置到新處）
        await send({"type": "toggle_pause"}); await until(lambda d: d["paused"], 5)
        await send({"type": "seek", "position": 200})
        d = await until(lambda d: d["current"] and d["current"]["position"] >= 199, 10)
        check("3 暫停中跳到 200 秒且維持暫停", 199 <= d["current"]["position"] < 204 and d["current"]["id"] == cid and d["paused"], f"pos={d['current']['position']} paused={d['paused']}")
        # 4. 超出長度 -> 夾在結尾之前，不會直接播完換歌
        await send({"type": "seek", "position": 99999}); await asyncio.sleep(1.5); await send({"type": "loop", "mode": "off"}); await asyncio.sleep(0.4)
        d = st["d"]
        check("4 超出長度：夾在結尾前（沒有被當作播完）", d["current"] and d["current"]["id"] == cid and d["current"]["position"] >= dur - 3, f"pos={d['current'] and d['current']['position']} dur={dur}")
        # 5. 單曲循環下跳轉不會把曲目重複排進佇列
        await send({"type": "loop", "mode": "single"}); await send({"type": "seek", "position": 10})
        await asyncio.sleep(1.5)
        d = st["d"]
        check("5 單曲循環下跳轉：佇列沒有多出東西", [t["id"] for t in d["queue"]] == q0 and d["current"]["id"] == cid, f"queue={[t['id'] for t in d['queue']]}")
        task.cancel()
    print(f"\n總結：{sum(res)}/{len(res)} 通過")
asyncio.run(asyncio.wait_for(main(), 120))


