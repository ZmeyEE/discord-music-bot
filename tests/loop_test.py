"""循環：單曲循環、列表循環、跳過與刪除正在播放的
Loop: single loop, queue loop, skipping and deleting the current track

用 tests/run_all.py 或 tests/run_relay.py 執行 / run it with tests/run_all.py or tests/run_relay.py
"""
import asyncio, aiohttp, json, time

URL = "http://127.0.0.1:8766/ws/777"
results = []

def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS" if ok else "FAIL"), name, detail, flush=True)

async def main():
    async with aiohttp.ClientSession() as s, s.ws_connect(URL) as ws:
        st = {}
        async def pump():
            async for m in ws:
                d = json.loads(m.data)
                if d["type"] == "state": st["d"] = d["data"]
                elif d["type"] == "toast": print("  toast:", d["text"], flush=True)
        task = asyncio.create_task(pump())
        send = lambda o: ws.send_str(json.dumps(o))

        async def until(pred, timeout=25, label=""):
            t = time.time()
            while time.time() - t < timeout:
                d = st.get("d")
                if d and pred(d): return d
                await asyncio.sleep(0.1)
            raise TimeoutError(label or "timeout")

        names = lambda d: [t["id"] for t in d["queue"]]
        cur = lambda d: d["current"]["id"] if d["current"] else None

        # 準備：Bilibili 直連 1 首 + YouTube 2 首
        await send({"type": "add", "query": "https://www.bilibili.com/video/av55185686"})
        await send({"type": "add", "query": "yt: lofi hip hop beats"})
        await send({"type": "add", "query": "yt: classical piano relaxing"})
        await send({"type": "add", "query": "yt: acoustic guitar instrumental"})
        d = await until(lambda d: d["current"] and not d["current"]["loading"] and len(d["queue"]) == 3, 60, "準備佇列")
        print("  準備完成：current=%s queue=%s" % (cur(d), names(d)), flush=True)

        # ---- A. 單曲循環：自然播完後應重播同一首，佇列不變 ----
        await send({"type": "loop", "mode": "single"})
        c0, q0 = cur(d), names(d)
        await asyncio.sleep(9)   # 模擬一首 4 秒 -> 這段時間內至少播完一次
        d = st["d"]
        check("A 單曲循環：播完後仍是同一首", cur(d) == c0, f"{c0} -> {cur(d)}")
        check("A 單曲循環：佇列沒有變動", names(d) == q0, f"{q0} -> {names(d)}")

        # ---- B. 單曲循環下按"下一首"：應真的跳到下一首，且舊曲不再回來 ----
        await send({"type": "skip"})
        d = await until(lambda d: cur(d) not in (c0, None) and d["current"] and not d["current"]["loading"], 20, "skip")
        c1 = cur(d)
        check("B 單曲循環下 skip：換到下一首", c1 != c0 and c1 == q0[0], f"now={c1} expect={q0[0]}")
        check("B 舊曲沒有被塞回佇列", c0 not in names(d), f"queue={names(d)}")

        # ---- C. 列表循環：播完的曲目要接到佇列最後 ----
        await send({"type": "loop", "mode": "queue"})
        await asyncio.sleep(0.3)
        n_before = len(st["d"]["queue"]) + 1   # 佇列 + 目前
        await asyncio.sleep(9)
        d = st["d"]
        n_after = len(d["queue"]) + (1 if d["current"] else 0)
        check("C 列表循環：總曲數不減少", n_after == n_before, f"{n_before} -> {n_after}")
        check("C 列表循環：播完的曲目輪到佇列後面（仍在輪替）", c1 in names(d) or cur(d) == c1, f"c1={c1} cur={cur(d)} queue={names(d)}")

        # ---- D. 立即播放：把佇列最後一張變成目前播放 ----
        d = st["d"]
        target = names(d)[-1]
        await send({"type": "play_now", "id": target})
        d = await until(lambda d: cur(d) == target, 20, "play_now")
        check("D 立即播放：目前曲目 = 指定卡片", cur(d) == target)


        # ---- G. 列表循環下"刪除正在播放"：不能被排回佇列 ----
        await send({"type": "loop", "mode": "queue"})
        await asyncio.sleep(0.3)
        await until(lambda d: d['current'] and not d['current']['loading'], 20, 'G prep')
        d = st["d"]; victim = cur(d); n0 = len(d["queue"]) + 1
        await send({"type": "remove_current"})
        d = await until(lambda d: cur(d) != victim and d["current"] and not d["current"]["loading"], 20, "remove_current")
        check("G 列表循環下刪除正在播放：換下一首", cur(d) != victim)
        check("G 被刪的曲目不在佇列也不在播放", victim not in names(d) and cur(d) != victim, f"queue={names(d)}")
        check("G 總曲數剛好少 1", len(d["queue"]) + 1 == n0 - 1, f"{n0} -> {len(d['queue']) + 1}")
        # ---- E. 關閉循環：播完後佇列會減少 ----
        await send({"type": "loop", "mode": "off"})
        await asyncio.sleep(0.3)
        total0 = len(st["d"]["queue"]) + 1
        await asyncio.sleep(9)
        d = st["d"]
        total1 = len(d["queue"]) + (1 if d["current"] else 0)
        check("E 關閉循環：總曲數減少", total1 < total0, f"{total0} -> {total1}")

        # ---- F. 暫停/繼續 ----
        if st["d"]["current"]:
            await send({"type": "toggle_pause"})
            d = await until(lambda d: d["paused"], 5, "pause")
            p1 = d["current"]["position"]
            await asyncio.sleep(1.5)
            check("F 暫停：伺服器回報 paused 且進度凍結", bool(st["d"]["current"]) and st["d"]["current"]["position"] == p1, f"pos={p1}")
            await send({"type": "toggle_pause"})
            await until(lambda d: not d["paused"], 5, "resume")
            check("F 繼續：paused 解除", True)

        task.cancel()
    print("\n總結：%d/%d 通過" % (sum(results), len(results)))

asyncio.run(asyncio.wait_for(main(), 240))



