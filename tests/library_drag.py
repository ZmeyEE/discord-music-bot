"""我的歌單的拖曳：用無頭 Chrome（真滑鼠）拖卡片排序、搬進左邊資料夾列、拖到右上角刪除區，歌曲排序與搬到另一張歌單
Library dragging: headless Chrome (real mouse) reorders cards, moves them onto the folder bar, deletes on the trash at the top right,
reorders songs and moves them to another playlist

需要 Chrome 或 Edge，找不到就略過。用 tests/run_all.py 執行 / needs Chrome or Edge (skipped otherwise); run it with tests/run_all.py
"""
import asyncio, base64, json, os, sys
import aiohttp
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp import Browser   # noqa: E402

BASE, DBG, GID, OWNER = "http://127.0.0.1:8766", "http://127.0.0.1:8767", 777, 9001
res = []
def check(n, ok, d=""): res.append(bool(ok)); print(("PASS" if ok else "FAIL"), n, str(d)[:220], flush=True)

HOOK = ("window.__sent = []; const S = WebSocket.prototype.send; WebSocket.prototype.send = function (d) { try { window.__sent.push(JSON.parse(d)); } catch (e) {} return S.call(this, d); };"
        "window.__errs = []; addEventListener('error', e => window.__errs.push(e.message)); addEventListener('unhandledrejection', e => window.__errs.push(String(e.reason)));")


async def seed(s, **q):
    async with s.get(f"{DBG}/libseed", params={"u": OWNER, **q}) as r: return await r.json()


async def pos(c, sel, nth=0):
    return await c.js("(() => { const e = document.querySelectorAll(%s)[%d]; if (!e) return null; const r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()" % (json.dumps(sel), nth))


async def drag(c, a, b, hold=None):
    """從 a 按下去、慢慢移到 b 再放開；hold = 放開前先量一次的 JS / press at a, move to b in steps, release; ``hold`` is JS measured just before releasing."""
    await c.mouse("mouseMoved", *a); await c.mouse("mousePressed", *a)
    steps = 14
    for i in range(1, steps + 1):
        await c.mouse("mouseMoved", a[0] + (b[0] - a[0]) * i / steps, a[1] + (b[1] - a[1]) * i / steps)
        await asyncio.sleep(0.03)
    await asyncio.sleep(0.25)
    mid = await c.js(hold) if hold else None
    if hold and os.environ.get("SHOT_DIR"):          # 要看畫面時：放開前截一張圖 / to look at it: a screenshot just before releasing
        shot = await c.call("Page.captureScreenshot", format="png")
        open(os.path.join(os.environ["SHOT_DIR"], f"drag_{len(res)}.png"), "wb").write(base64.b64decode(shot["data"]))
    await c.mouse("mouseReleased", *b)
    await asyncio.sleep(0.8)
    return mid


names = lambda c: c.js("[...document.querySelectorAll('.lib-card .lib-name')].map(n => n.textContent)")
songs = lambda c: c.js("[...document.querySelectorAll('.lib-song .t b')].map(n => n.textContent)")
sent = lambda c, kind: c.js("window.__sent.filter(m => m.type === %s)" % json.dumps(kind))


async def main():
    async with aiohttp.ClientSession() as s:
        await seed(s, n=5, name="甲", reset=1)
        await seed(s, n=3, name="乙")
        await seed(s, n=4, name="丙")
        f = await seed(s, folder="資料夾")
        await seed(s, n=2, name="丁", parent=f["id"])
        async with s.get(f"{DBG}/fill", params={"n": 3, "clear": 1}) as r: await r.read()
        async with Browser(s) as c:
            if c is None:
                print("SKIP 找不到 Chrome 或 Edge，略過 / no Chrome or Edge found, skipped"); print("\n總結：0/0 通過（略過）"); return
            await c.call("Page.addScriptToEvaluateOnNewDocument", source=HOOK)
            await c.call("Emulation.setDeviceMetricsOverride", width=1400, height=900, deviceScaleFactor=1, mobile=False)
            await c.call("Emulation.setEmulatedMedia", features=[{"name": "prefers-reduced-motion", "value": "no-preference"}])
            await c.call("Page.navigate", url=f"{BASE}/g/{GID}")
            await asyncio.sleep(2.5)
            await c.mouse("mouseMoved", *await pos(c, "#btnLibrary")); await c.click(*await pos(c, "#btnLibrary"))
            await asyncio.sleep(1)

            # 1. 版面 / layout
            check("1a 左邊有資料夾列：我的歌單、資料夾，展開後看到裡面的歌單", await c.js("document.querySelectorAll('#libTree .lt-row').length") >= 3, await c.js("[...document.querySelectorAll('#libTree .lt-row')].map(r => r.textContent)"))
            check("1b 刪除區平常看不到，只有拖曳時才出現", await c.js("getComputedStyle(document.getElementById('libTrash')).visibility") == "hidden")
            check("1c 卡片順序：甲 乙 丙 資料夾", await names(c) == ["甲", "乙", "丙", "資料夾"], await names(c))

            # 2. 卡片排序：把丙拖到最前面 / reorder: drag 丙 to the front
            mid = await drag(c, await pos(c, ".lib-card", 2), await pos(c, ".lib-card", 0), "(() => { const g = document.querySelector('.sortable-fallback'); const r = g && g.getBoundingClientRect(); return {trash: getComputedStyle(document.getElementById('libTrash')).visibility, ghost: !!g, inDialog: !!(g && g.closest('#libDialog')), top: r && r.top, left: r && r.left}; })()")
            check("2a 拖曳中：浮動的卡片在視窗裡（不會被蓋住）、刪除區浮現", mid and mid["ghost"] and mid["inDialog"] and mid["trash"] == "visible", mid)
            m = await sent(c, "lib_move")
            check("2b 放開後送出 lib_move，帶 index 0", m and m[-1].get("index") == 0 and m[-1]["to"] == "root" and len(m[-1]["ids"]) == 1, m[-1:] if m else m)
            check("2c 伺服器回來後順序變成：丙 甲 乙 資料夾", await names(c) == ["丙", "甲", "乙", "資料夾"], await names(c))
            check("2d 拖完沒有誤進入歌單（還在資料夾列表）", await c.js("!!document.querySelector('.lib-grid')"))

            # 3. 拖到左邊資料夾列的"資料夾" / drop on the folder in the bar
            n_before = await c.js("document.querySelectorAll('#libTree .lt-row').length")
            fr = await c.js("(() => { const r = [...document.querySelectorAll('#libTree .lt-row')].find(x => x.dataset.kind === 'folder' && x.textContent.includes('資料夾')); const b = r.getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2]; })()")
            mid = await drag(c, await pos(c, ".lib-card", 1), fr, "document.querySelector('#libTree .drop-over') ? document.querySelector('#libTree .drop-over').textContent : null")
            check("3a 拖到資料夾列時，那一列有高亮", mid and "資料夾" in mid, mid)
            m = await sent(c, "lib_move")
            folder_id = f["id"]
            check("3b 放開後送出 lib_move，目的地是那個資料夾", m and m[-1]["to"] == folder_id and "index" not in m[-1], m[-1:] if m else m)
            check("3c 甲被搬走：根目錄只剩 丙 乙 資料夾", await names(c) == ["丙", "乙", "資料夾"], await names(c))

            # 4. 拖到刪除區 / drop on the trash
            tr = await pos(c, "#libTrash")
            mid = await drag(c, await pos(c, ".lib-card", 1), await c.js("(() => { const r = document.getElementById('libTrash').getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()"), "document.getElementById('libTrash').classList.contains('drop-over')")
            check("4a 拖到刪除區時，刪除區有高亮", mid is True, mid)
            m = await sent(c, "lib_delete")
            check("4b 放開後送出 lib_delete（乙）", m and len(m[-1]["ids"]) == 1, m[-1:] if m else m)
            check("4c 乙被刪掉：剩 丙 資料夾", await names(c) == ["丙", "資料夾"], await names(c))
            check("4d 放開後刪除區又收起來", await c.js("getComputedStyle(document.getElementById('libTrash')).visibility") == "hidden")

            # 5. 歌曲排序、搬到另一張歌單、從歌單拖出刪除 / songs: reorder, move to another playlist, delete
            await c.click(*await pos(c, ".lib-card", 0)); await asyncio.sleep(1)     # 打開丙（4 首）/ open 丙 (4 songs)
            check("5a 打開丙：4 首歌", len(await songs(c)) == 4, await songs(c))
            first = (await songs(c))[0]
            mid = await drag(c, await pos(c, ".lib-song", 3), await pos(c, ".lib-song", 0))
            m = await sent(c, "lib_song_order")
            check("5b 把第 4 首拖到最前面：送出 lib_song_order from 3 to 0", m and m[-1]["from"] == 3 and m[-1]["to"] == 0, m[-1:] if m else m)
            now = await songs(c)
            check("5c 順序真的變了：原本第一首變第二首", len(now) == 4 and now[1] == first and now[0] != first, now)
            row = await c.js("(() => { const r = [...document.querySelectorAll('#libTree .lt-row')].find(x => x.dataset.kind === 'playlist' && x.textContent.includes('丁')); if (!r) return null; r.scrollIntoView(); const b = r.getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2]; })()")
            if row is None:                                    # 丁在資料夾裡，先展開 / 丁 is inside the folder: expand it
                await c.click(*await c.js("(() => { const r = [...document.querySelectorAll('#libTree .lt-row')].find(x => x.dataset.kind === 'folder' && x.textContent.includes('資料夾')); const b = r.querySelector('.lt-caret').getBoundingClientRect(); return [b.left + 4, b.top + 4]; })()")); await asyncio.sleep(0.4)
                row = await c.js("(() => { const r = [...document.querySelectorAll('#libTree .lt-row')].find(x => x.dataset.kind === 'playlist' && x.textContent.includes('丁')); const b = r.getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2]; })()")
            await drag(c, await pos(c, ".lib-song", 0), row)
            m = await sent(c, "lib_song_move")
            check("5d 把一首歌拖到資料夾列的丁：送出 lib_song_move", m and m[-1]["to"] and m[-1]["indexes"] == [0], m[-1:] if m else m)
            check("5e 丙剩 3 首", len(await songs(c)) == 3, await songs(c))
            tr = await c.js("(() => { const r = document.getElementById('libTrash').getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()")
            await drag(c, await pos(c, ".lib-song", 0), tr)
            m = await sent(c, "lib_remove_songs")
            check("5f 把一首歌拖到刪除區：送出 lib_remove_songs", m and m[-1]["indexes"] == [0], m[-1:] if m else m)
            check("5g 丙剩 2 首", len(await songs(c)) == 2, await songs(c))

            # 6. 左邊資料夾列點選 / clicking the bar
            await c.click(*await c.js("(() => { const r = [...document.querySelectorAll('#libTree .lt-row')].find(x => x.dataset.kind === 'playlist' && x.textContent.includes('丁')); const b = r.getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2]; })()")); await asyncio.sleep(1)
            check("6a 點資料夾列的丁：打開那張歌單，裡面 3 首（原本 2 首 + 搬來 1 首）", len(await songs(c)) == 3, await songs(c))
            await c.click(*await c.js("(() => { const b = document.querySelector('#libTree .lt-row').getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2]; })()")); await asyncio.sleep(0.8)
            check("6b 點最上面的\"我的歌單\"：回到根目錄", await names(c) == ["丙", "資料夾"], await names(c))
            # 8. 最上層收合、左邊資料夾列自己也能拖、卡片放在列的上緣＝插在那個位置、卡片放在資料夾卡片中央＝放進去
            # 8. the top level collapses, the folder bar rows can be dragged, a card dropped on a row's top edge lands at that spot, a card dropped on the middle of a folder card goes inside
            rows = lambda: c.js("[...document.querySelectorAll('#libTree .lt-row')].map(r => r.textContent.trim())")
            rowpt = lambda txt, f: c.js("(() => { const r = [...document.querySelectorAll('#libTree .lt-row')].find(x => x.textContent.includes(%s)); const b = r.getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height * %s]; })()" % (json.dumps(txt), f))
            caret = await c.js("(() => { const b = document.querySelector('#libTree .lt-row[data-root] .lt-caret').getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2]; })()")
            await c.click(*caret); await asyncio.sleep(0.4)
            check("8a 按最上層的箭頭：整棵收起來，只剩一列", len(await rows()) == 1, await rows())
            await c.click(*caret); await asyncio.sleep(0.4)
            check("8b 再按一次：展開回來", len(await rows()) >= 3, await rows())
            mid = await drag(c, await rowpt("資料夾", 0.5), await rowpt("丙", 0.1), "document.querySelector('#libTree .drop-before') ? document.querySelector('#libTree .drop-before').textContent.trim() : null")
            check("8c 拖資料夾列到丙的上緣：丙那一列顯示插入線", mid == "丙", mid)
            m = await sent(c, "lib_move")
            check("8d 放開後送出 lib_move，放在根目錄第 0 個", m and m[-1]["to"] == "root" and m[-1].get("index") == 0 and m[-1]["ids"] == [f["id"]], m[-1:] if m else m)
            check("8e 左邊與右邊都變成：資料夾 丙", await names(c) == ["資料夾", "丙"] and (lambda r: [i for i, t in enumerate(r) if "資料夾" in t][0] < r.index("丙"))(await rows()), [await names(c), await rows()])
            await drag(c, await pos(c, ".lib-card", 1), await rowpt("資料夾", 0.1))
            m = await sent(c, "lib_move")
            check("8f 把丙的卡片拖到左邊資料夾列的上緣：放在根目錄第 0 個", m and m[-1]["to"] == "root" and m[-1].get("index") == 0, m[-1:] if m else m)
            check("8g 卡片跟著動：丙 資料夾", await names(c) == ["丙", "資料夾"], await names(c))
            mid = await drag(c, await pos(c, ".lib-card", 0), await pos(c, ".lib-card.folder"), "document.querySelector('.lib-card.drop-over') ? document.querySelector('.lib-card.drop-over .lib-name').textContent : null")
            check("8h 把卡片拖到資料夾卡片的中央：那張卡片高亮（不是互換位置）", mid == "資料夾", mid)
            m = await sent(c, "lib_move")
            check("8i 放開後送出 lib_move，目的地是那個資料夾", m and m[-1]["to"] == f["id"] and "index" not in m[-1], m[-1:] if m else m)
            check("8j 丙被放進資料夾：根目錄只剩資料夾", await names(c) == ["資料夾"], await names(c))

            errs = await c.js("window.__errs")
            check("7 整個過程頁面沒有 JS 錯誤", not errs, errs)

    ok = sum(res)
    print(f"\n總結：{ok}/{len(res)} 通過" + ("" if ok == len(res) else "（有失敗）"))
    sys.exit(0 if ok == len(res) else 1)

asyncio.run(main())
