"""看板的清單效能：用無頭 Chrome（真的瀏覽器、真的滑鼠事件）量 2500 張卡片時的節點數、捲動、刪除、拖曳的畫面更新率
Dashboard list performance: headless Chrome (a real browser, real mouse events) measures node count, scrolling, deleting and
dragging frame rates with 2500 cards

需要電腦上有 Chrome 或 Edge，找不到就略過（不算失敗）。用 tests/run_all.py 執行 / needs Chrome or Edge installed (skipped if none); run it with tests/run_all.py
"""
import asyncio, json, os, sys, time
import aiohttp
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE, DBG, GID, N = "http://127.0.0.1:8766", "http://127.0.0.1:8767", 777, 2500
FPS_TARGET = 55          # 拖曳時的平均畫面更新率要到這個（60 為滿分，留一點量測誤差）/ the average frame rate during a drag must reach this (60 is full marks; a little room for measurement error)
res = []
def check(n, ok, d=""): res.append(bool(ok)); print(("PASS" if ok else "FAIL"), n, str(d)[:190], flush=True)

from cdp import CDP, Browser, find_browser   # noqa: E402

FRAMES_JS = """
window.__fr = []; window.__run = true;
(function loop(t){ if (!window.__run) return; window.__fr.push(t); requestAnimationFrame(loop); })(performance.now());
"""
def stats(frames):
    """畫面時間列表 -> (平均 fps, 最長一格毫秒, 超過 25 毫秒的格數) / frame timestamps -> (average fps, longest frame in ms, frames over 25 ms)"""
    d = [b - a for a, b in zip(frames, frames[1:])]
    if not d: return 0, 0, 0
    return 1000 * len(d) / sum(d), max(d), sum(1 for x in d if x > 25)

async def measure(c, action):
    await c.js(FRAMES_JS); await asyncio.sleep(0.15)
    t0 = await c.js("window.__fr.length")
    await action()
    await asyncio.sleep(0.15)
    fr = await c.js("window.__run = false; window.__fr.slice(%d)" % t0)
    return stats(fr)

async def clip_box(c, h):
    """清單真的看得到的上下邊（被面板切掉的部分滑鼠點不到）/ the top and bottom of what is really visible of the list (the part the panel clips can't be clicked)"""
    top, bottom = await c.js("(() => { const r = document.getElementById('queue').getBoundingClientRect(); return [Math.max(r.top, 0), Math.min(r.bottom, innerHeight)]; })()")
    return top, bottom

async def visible_cards(c):
    return await c.js("""[...document.querySelectorAll('#queue .card')].map(e => { const r = e.getBoundingClientRect(); return {id: e.dataset.id, idx: +e.querySelector('.idx').textContent, top: r.top, bottom: r.bottom, x: r.left + r.width / 2}; })""")

async def run_viewport(s, c, w, h, label):
    await c.call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=False)
    await c.call("Page.navigate", url=f"{BASE}/g/{GID}")
    for _ in range(80):
        await asyncio.sleep(0.15)
        if await c.js("document.querySelectorAll('#queue .card').length") > 5: break
    qx, qy = await c.js("(() => { const r = document.getElementById('queue').getBoundingClientRect(); return [r.left + r.width / 2, Math.min(innerHeight, r.bottom) / 2 + Math.max(0, r.top) / 2]; })()")   # 清單中央，滾輪要對著它 / the middle of the list; the wheel must point at it
    n_cards = await c.js("document.querySelectorAll('#queue .card').length")
    nodes = await c.js("document.querySelectorAll('*').length")
    check(f"{label} A1 一開始只畫看得到的卡片（共 {N} 首）", 5 < n_cards < 60 and await c.js("+document.getElementById('queueCount').textContent") == N, n_cards)
    check(f"{label} A2 網頁節點數不到 3000（以前 1000 張卡片就 2 萬多個）", nodes < 3000, nodes)

    # 往下載入到 2500 首：靠滾輪一路捲到底，網頁會一批一批去要 / load all 2500 by wheeling down; the page asks for batches
    for _ in range(600):
        await c.wheel(qx, qy, 1500)
        await asyncio.sleep(0.04)
        if await c.js("import('/static/js/store.js').then(m => m.S.state.queue.length)") >= N: break
    await asyncio.sleep(0.5)
    loaded = await c.js("import('/static/js/store.js').then(m => m.S.state.queue.length)")
    check(f"{label} A3 捲到底把 {N} 首全部載入", loaded == N, loaded)
    n_cards = await c.js("document.querySelectorAll('#queue .card').length")
    nodes = await c.js("document.querySelectorAll('*').length")
    check(f"{label} A4 全部載入後，畫出來的還是只有幾十張", n_cards < 60 and nodes < 3000, (n_cards, nodes))

    # 捲動：捲到清單中間，看到的卡片序號要和位置對得上 / scroll to the middle: the visible card numbers must match the position
    async def scroll_around():
        for dy in [-9000, -9000, -9000, -9000, 6000, 6000, -3000, 12000, -20000]:
            for _ in range(6):
                await c.wheel(qx, qy, dy / 6); await asyncio.sleep(0.016)
    fps, worst, slow = await measure(c, scroll_around)
    check(f"{label} B1 來回捲動 {N} 張的清單：平均 {fps:.0f} fps，最長一格 {worst:.0f} ms", fps >= FPS_TARGET and worst < 100, (round(fps), round(worst), slow))
    await c.js("document.getElementById('queue').scrollTop = 0; window.scrollTo(0, 0)")
    await asyncio.sleep(0.4)
    for _ in range(40): await c.wheel(qx, qy, 1200); await asyncio.sleep(0.03)
    await asyncio.sleep(0.5)
    cards = await visible_cards(c)
    seq = [x["idx"] for x in cards]
    check(f"{label} B2 捲到中間：畫出的卡片序號連續且位置在畫面上", seq == list(range(seq[0], seq[0] + len(seq))) and seq[0] > 100 and any(0 <= x["top"] < h for x in cards), (seq[:2], seq[-2:]))
    ctop, cbot = await clip_box(c, h)
    pos = [x for x in cards if ctop + 8 < x["top"] and x["bottom"] < cbot - 8]
    check(f"{label} B3 畫面上的卡片不是空白（有卡片落在可視範圍）", len(pos) >= 3, len(pos))

    # 刪除：點中間一張的 ×，量到下一張往上補齊要多久、期間有沒有卡頓 / delete: click the × of one card, time the next one moving up and look for jank
    target = pos[len(pos) // 2]
    before = {x["id"]: x["idx"] for x in cards}
    nxt_id = next(x["id"] for x in cards if x["idx"] == target["idx"] + 1)
    async def delete_one():
        await c.mouse("mouseMoved", target["x"], (target["top"] + target["bottom"]) / 2)
        await asyncio.sleep(0.1)
        bx = await c.js(f"(() => {{ const b = document.querySelector('#queue .card[data-id=\"{target['id']}\"] .actions .x'); const r = b.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }})()")
        await c.mouse("mouseMoved", bx[0], bx[1]); await c.mouse("mousePressed", bx[0], bx[1]); await c.mouse("mouseReleased", bx[0], bx[1])
        t0 = time.perf_counter()
        for _ in range(100):
            await asyncio.sleep(0.01)
            now = await c.js(f"(() => {{ const e = document.querySelector('#queue .card[data-id=\"{nxt_id}\"] .idx'); return e ? +e.textContent : -1; }})()")
            if now == before[nxt_id] - 1: break
        delete_one.ms = (time.perf_counter() - t0) * 1000
    fps, worst, slow = await measure(c, delete_one)
    check(f"{label} C1 刪除一張：下一張 {delete_one.ms:.0f} ms 內補上來（序號少 1）", delete_one.ms < 400, round(delete_one.ms))
    check(f"{label} C2 刪除當下沒有卡頓：最長一格 {worst:.0f} ms", worst < 100, (round(fps), round(worst), slow))
    total = await c.js("+document.getElementById('queueCount').textContent")
    check(f"{label} C3 清單少了一首（{N - 1}）", total == N - 1, total)
    async with s.get(f"{DBG}/fill", params={"n": N, "clear": 1}) as r: await r.read()   # 重新放滿 / refill
    await asyncio.sleep(1.0)

    # 拖曳：按住一張卡片往下拖 300px 再放開，量拖曳期間的畫面更新率；然後確認伺服器真的換了位置
    # drag: hold a card, drag it 300 px down, release; measure the frame rate during the drag and check the server really moved it
    await c.js("document.getElementById('queue').scrollTop = 0; window.scrollTo(0, 0)")
    for _ in range(25): await c.wheel(qx, qy, 900); await asyncio.sleep(0.03)
    await asyncio.sleep(0.6)
    cards = await visible_cards(c)
    ctop, cbot = await clip_box(c, h)
    pos = [x for x in cards if ctop + 8 < x["top"] and x["bottom"] + 300 < cbot - 8] or [x for x in cards if ctop + 8 < x["top"] and x["bottom"] < cbot - 8]
    src = pos[0]; y0 = (src["top"] + src["bottom"]) / 2
    await c.js("import('/static/js/dragdrop.js').then(m => { const o = m.sortQueue.options.onEnd; m.sortQueue.options.onEnd = (e) => { window.__end = {same: e.from === e.to, o: e.oldDraggableIndex, n: e.newDraggableIndex, oi: e.oldIndex, ni: e.newIndex}; return o(e); }; })")
    async def drag():
        await c.mouse("mouseMoved", src["x"], y0); await c.mouse("mousePressed", src["x"], y0)
        reach = min(300, cbot - 8 - y0)        # 窄螢幕下面空間不夠就少拖一點 / on a short screen drag a little less
        for i in range(1, 61):
            await c.mouse("mouseMoved", src["x"], y0 + reach * i / 60, buttons=1)
            await asyncio.sleep(0.016)
        await c.mouse("mouseReleased", src["x"], y0 + reach)
        await asyncio.sleep(0.5)
    fps, worst, slow = await measure(c, drag)
    check(f"{label} D1 拖曳排序（{N} 張）：平均 {fps:.0f} fps，最長一格 {worst:.0f} ms", fps >= FPS_TARGET and worst < 100, (round(fps), round(worst), slow))
    st = await c.js("import('/static/js/store.js').then(m => m.S.state.queue.findIndex(t => t.id === '%s'))" % src["id"])
    dom = await c.js("[...document.querySelectorAll('#queue .card')].findIndex(e => e.dataset.id === '%s')" % src["id"])
    check(f"{label} D2 放開後伺服器收到新位置（{src['idx'] - 1} -> {st}）", st > src["idx"] - 1 + 1, (st, "畫面上的位置", dom, "結束事件", await c.js("JSON.stringify(window.__end || null)"), "送出", await c.js("JSON.stringify(window.__sent.filter(m => m.type === 'move' || m.type === 'remove').slice(-3))")))
    await c.js("document.body.classList.contains('dragging') ? 1 : 0")
    check(f"{label} D3 放開後拖曳狀態有結束", not await c.js("document.body.classList.contains('dragging')"))

async def main():
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{DBG}/fill", params={"n": N, "clear": 1}) as r: await r.read()
        async with Browser(s) as c:
            if c is None:
                print("SKIP 找不到 Chrome 或 Edge，略過 / no Chrome or Edge found, skipped"); print("\n總結：0/0 通過（略過）"); return
            # 記下網頁送出的每一則訊息，之後可以檢查它有沒有送對 / record every message the page sends so we can check what it sent
            await c.call("Page.addScriptToEvaluateOnNewDocument", source="window.__sent = []; const _s = WebSocket.prototype.send; WebSocket.prototype.send = function (d) { try { window.__sent.push(JSON.parse(d)); } catch {} return _s.call(this, d); };")
            await run_viewport(s, c, 1400, 900, "[寬]")
            async with s.get(f"{DBG}/fill", params={"n": N, "clear": 1}) as r: await r.read()
            await run_viewport(s, c, 420, 880, "[窄]")
    print(f"\n總結：{sum(res)}/{len(res)} 通過")
asyncio.run(asyncio.wait_for(main(), 300))
