"""音質：預設值、可選項目、切換後位元率生效並從原位置接續
Quality: default, choices, the new bitrate takes effect and playback resumes from the same position

用 tests/run_all.py 或 tests/run_relay.py 執行 / run it with tests/run_all.py or tests/run_relay.py
"""
import asyncio, aiohttp, json, time
res = []
def check(n, ok, d=""): res.append(ok); print(("PASS" if ok else "FAIL"), n, d, flush=True)
async def main():
    async with aiohttp.ClientSession() as s, s.ws_connect("http://127.0.0.1:8766/ws/777") as ws:
        st = {}; toasts = []
        async def pump():
            async for m in ws:
                d = json.loads(m.data)
                if d["type"] == "state": st["d"] = d["data"]
                elif d["type"] == "toast": toasts.append(d["text"])
        task = asyncio.create_task(pump()); send = lambda o: ws.send_str(json.dumps(o))
        async def until(p, t=25):
            e = time.time() + t
            while time.time() < e:
                if st.get("d") and p(st["d"]): return st["d"]
                await asyncio.sleep(0.1)
            raise TimeoutError()
        await asyncio.sleep(0.5)
        await send({"type": "stop"}); await asyncio.sleep(0.6)
        await send({"type": "add", "query": "https://www.bilibili.com/video/av55185686"})
        d = await until(lambda d: d["current"] and not d["current"]["loading"] and d["current"]["duration"], 40)
        cid = d["current"]["id"]
        check("0 預設音質為 192", d["quality"]["kbps"] == 192 and d["current"]["bitrate"] == 192, f"{d['quality']} bitrate={d['current']['bitrate']}")
        check("0 選項為 128/192/256/320/510", d["quality"]["choices"] == [128, 192, 256, 320, 510])
        await send({"type": "seek", "position": 120}); await until(lambda d: d["current"]["position"] >= 119, 10)
        # 1. 切到 256：同一首、位置保留、位元率變 256
        await send({"type": "quality", "kbps": 256})
        d = await until(lambda d: d["quality"]["kbps"] == 256 and d["current"] and d["current"]["bitrate"] == 256, 10)
        check("1 切到 256：位元率生效", d["current"]["bitrate"] == 256)
        check("1 仍是同一首且從原位置接續", d["current"]["id"] == cid and 119 <= d["current"]["position"] < 126, f"pos={d['current']['position']}")
        check("1 回傳提示訊息", any("256" in t for t in toasts), str(toasts[-1:]))
        # 2. 暫停中切換：維持暫停
        await send({"type": "toggle_pause"}); await until(lambda d: d["paused"], 5)
        await send({"type": "quality", "kbps": 320})
        d = await until(lambda d: d["current"] and d["current"]["bitrate"] == 320, 10)
        await asyncio.sleep(0.5)
        check("2 暫停中切到 320：維持暫停、位元率生效", st["d"]["paused"] and st["d"]["current"]["bitrate"] == 320, f"paused={st['d']['paused']}")
        # 3. 不合法的值
        n = len(toasts)
        await send({"type": "quality", "kbps": 999}); await asyncio.sleep(0.5)
        check("3 拒絕不合法的音質（999）", st["d"]["quality"]["kbps"] == 320 and len(toasts) > n and "不支援" in toasts[-1], toasts[-1])
        await send({"type": "quality", "kbps": "abc"}); await asyncio.sleep(0.5)
        check("3 拒絕非數字", st["d"]["quality"]["kbps"] == 320 and "不支援" in toasts[-1])
        # 4. 還原預設
        await send({"type": "quality", "kbps": 192}); await asyncio.sleep(1.0)
        check("4 切回 192", st["d"]["quality"]["kbps"] == 192)
        task.cancel()
    print(f"\n總結：{sum(res)}/{len(res)} 通過")
asyncio.run(asyncio.wait_for(main(), 120))


