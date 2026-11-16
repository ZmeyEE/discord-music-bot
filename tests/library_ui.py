"""我的歌單的介面：用無頭 Chrome（真滑鼠）走一遍選取、存成歌單、資料夾、播放選單、加入歌單、開啟動畫、四種語言、手機寬度
The library screens: headless Chrome (real mouse) goes through select mode, saving a playlist, folders, the play menu, add-to-playlist,
the opening animation, the four languages and a phone width

需要 Chrome 或 Edge，找不到就略過。用 tests/run_all.py 執行 / needs Chrome or Edge (skipped otherwise); run it with tests/run_all.py
"""
import asyncio, json, os, sys
import aiohttp
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp import Browser   # noqa: E402

BASE, DBG, GID = "http://127.0.0.1:8766", "http://127.0.0.1:8767", 777
res = []
def check(n, ok, d=""): res.append(bool(ok)); print(("PASS" if ok else "FAIL"), n, str(d)[:200], flush=True)

SENT = "window.__sent"
HOOK = "window.__errs = []; addEventListener('error', e => window.__errs.push(e.message)); addEventListener('unhandledrejection', e => window.__errs.push(String(e.reason))); window.__opened = []; window.open = (u) => { window.__opened.push(u); return null; }; window.__sent = []; const _s = WebSocket.prototype.send; WebSocket.prototype.send = function (d) { try { window.__sent.push(JSON.parse(d)); } catch {} return _s.call(this, d); };"

async def center(c, sel):
    """元素中央的座標 / the centre of an element"""
    return await c.js("(() => { const e = document.querySelector(%s); if (!e) return null; e.scrollIntoView({block: 'nearest'}); const r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()" % json.dumps(sel))

async def click(c, sel, settle=0.35):
    pos = await center(c, sel)
    if pos is None: raise RuntimeError("找不到 " + sel)
    await c.click(*pos); await asyncio.sleep(settle)

async def text(c, sel): return await c.js("(document.querySelector(%s) || {}).textContent" % json.dumps(sel))
async def count(c, sel): return await c.js("document.querySelectorAll(%s).length" % json.dumps(sel))
async def sent(c, kind): return await c.js("%s.filter(m => m.type === %s)" % (SENT, json.dumps(kind)))
async def fill_name(c, value):
    await c.js("(() => { const i = document.getElementById('nameInput'); i.value = ''; i.focus(); })()")
    await c.type(value)
    await click(c, "#nameOk", 0.7)

async def main():
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{DBG}/fill", params={"n": 12, "clear": 1}) as r: await r.read()
        async with Browser(s) as c:
            if c is None:
                print("SKIP 找不到 Chrome 或 Edge，略過 / no Chrome or Edge found, skipped"); print("\n總結：0/0 通過（略過）"); return
            await c.call("Page.addScriptToEvaluateOnNewDocument", source=HOOK)
            await c.call("Emulation.setDeviceMetricsOverride", width=1400, height=900, deviceScaleFactor=1, mobile=False)
            # Windows 若關掉了動畫效果，瀏覽器會自動要求"減少動態"；這裡明確要求有動畫才能測動畫 / Windows with animations turned off makes the browser ask for reduced motion; ask for motion explicitly to test the animations
            await c.call("Emulation.setEmulatedMedia", features=[{"name": "prefers-reduced-motion", "value": "no-preference"}])
            await c.call("Page.navigate", url=f"{BASE}/g/{GID}")
            for _ in range(60):
                await asyncio.sleep(0.2)
                if await count(c, "#queue .card") >= 5: break
            check("1a 看板載入：待播清單有卡片、歌單與選取按鈕都在", await count(c, "#queue .card") >= 5 and await count(c, "#btnLibrary") == 1 and await count(c, "#btnSelect") == 1)
            check("1b 每張卡片都有\"加入歌單\"與勾勾框", await count(c, "#queue .card .actions button") >= 3 * 5 and await count(c, "#queue .card .pick") >= 5)

            # 2. 選取模式 / select mode
            await click(c, "#btnSelect")
            check("2a 按選取：進入選取模式、出現選取列", await c.js("document.querySelector('.col-queue').classList.contains('selecting')") and await c.js("getComputedStyle(document.getElementById('selBar')).display") != "none")
            for i in (1, 2, 3): await click(c, f"#queue .card:nth-of-type({i + 1})", 0.15)
            check("2b 點三張卡片：三張被勾選，選取列顯示已選 3 首", await count(c, "#queue .card.selected") == 3 and "3" in await text(c, "#selCount"), await text(c, "#selCount"))
            await click(c, "#selSave")
            check("2c 按\"存成歌單\"：跳出取名字的視窗", await c.js("document.getElementById('nameDialog').open"))
            await fill_name(c, "晨跑")
            m = await sent(c, "lib_save")
            check("2d 取名後送出 lib_save，帶 3 首的 id 與名字", m and m[-1]["name"] == "晨跑" and len(m[-1]["ids"]) == 3, m[-1:] if m else m)
            check("2e 存完離開選取模式", not await c.js("document.querySelector('.col-queue').classList.contains('selecting')") and await count(c, "#queue .card.selected") == 0)

            # 3. 歌單視窗與開啟動畫 / the library dialog and its animation
            await click(c, "#btnLibrary", 0.15)
            anim = await c.js("getComputedStyle(document.querySelector('#libBox')).animationName")
            await asyncio.sleep(0.6)
            check("3a 開啟歌單視窗：有開啟動畫（libOpen）", await c.js("document.getElementById('libDialog').open") and anim == "libOpen", anim)
            check("3b 看得到剛存的歌單卡片：名稱與 3 首", await count(c, ".lib-card.playlist") == 1 and "晨跑" in await text(c, ".lib-card .lib-name") and "3" in await text(c, ".lib-card .lib-sub"), await text(c, "#libBody"))
            box = await c.js("(() => { const r = document.getElementById('libBox').getBoundingClientRect(); return [r.width, r.height, innerWidth, innerHeight]; })()")
            check("3c 視窗大小合理（沒有超出畫面）", 300 < box[0] <= box[2] and 300 < box[1] <= box[3], box)

            # 4. 打開歌單：歌曲列 / open the playlist: song rows
            await click(c, ".lib-card.playlist", 0.8)
            check("4a 點歌單：看到 3 首歌的列、麵包屑多一層", await count(c, ".lib-song") == 3 and await count(c, "#libCrumbs button") == 2, await text(c, "#libCrumbs"))
            await click(c, ".lib-song:nth-child(1) .x", 0.8)
            m = await sent(c, "lib_remove_songs")
            check("4b 按歌旁的 ×：送出 lib_remove_songs，歌單剩 2 首", m and m[-1]["indexes"] == [0] and await count(c, ".lib-song") == 2, await count(c, ".lib-song"))
            await click(c, "#libUp", 0.5)
            check("4c 按上一層：回到資料夾畫面", await count(c, ".lib-card") == 1 and await count(c, ".lib-song") == 0)

            # 5. 選取歌單建立資料夾、進資料夾 / select a playlist and make a folder, then go into it
            buttons = await c.js("[...document.querySelectorAll('#libBar button')].map(b => b.textContent)")
            sel_i = next(i for i, t in enumerate(buttons) if t in ("選取", "Select"))
            await click(c, f"#libBar button:nth-child({sel_i + 1})", 0.3)
            await click(c, ".lib-card.playlist", 0.3)
            check("5a 選取模式：點歌單卡片被勾選，工具列變成建立資料夾／刪除／取消", await count(c, ".lib-card.selected") == 1 and await count(c, "#libBar button") == 3, await c.js("[...document.querySelectorAll('#libBar button')].map(b => b.textContent)"))
            await click(c, "#libBar button:nth-child(1)", 0.3)
            await fill_name(c, "運動")
            m = await sent(c, "lib_folder")
            check("5b 建立資料夾：送出 lib_folder，帶選取的歌單 id", m and m[-1]["name"] == "運動" and len(m[-1]["ids"]) == 1, m[-1:] if m else m)
            check("5c 畫面上變成一張資料夾卡片（資料夾圖示）", await count(c, ".lib-card.folder") == 1 and await count(c, ".lib-card.playlist") == 0 and "運動" in await text(c, ".lib-card.folder .lib-name"), await text(c, "#libBody"))
            await click(c, ".lib-card.folder", 0.1)
            check("5d 點資料夾：卡片有打開的動畫", await count(c, ".lib-card.opening") == 1)
            await asyncio.sleep(0.7)
            check("5e 進到資料夾：看到裡面的歌單、麵包屑是 我的歌單 › 運動", await count(c, ".lib-card.playlist") == 1 and "運動" in await text(c, "#libCrumbs"), await text(c, "#libCrumbs"))
            # 巢狀：在資料夾裡再建資料夾 / nesting: a folder inside the folder
            nf = next(i for i, t in enumerate(await c.js("[...document.querySelectorAll('#libBar button')].map(b => b.textContent)")) if "資料夾" in t or "Folder" in t)
            await click(c, f"#libBar button:nth-child({nf + 1})", 0.3)
            await fill_name(c, "內層")
            check("5f 資料夾裡可以再建資料夾（巢狀）", await count(c, ".lib-card.folder") == 1 and "內層" in await text(c, ".lib-card.folder .lib-name"), await text(c, "#libBody"))

            # 6. 播放選單 / the play menu
            await click(c, "#libCrumbs button:nth-child(1)", 0.6)
            await click(c, ".lib-card.folder .lib-act button:nth-child(1)", 0.3)
            items = await c.js("[...document.querySelectorAll('.lib-menu button')].map(b => b.textContent)")
            check("6a 資料夾的播放選單有 5 個選項（含兩種循環）", len(items) == 5 and any("跨資料夾" in t for t in items) and any("資料夾循環" in t for t in items), items)
            pos = await c.js("(() => { const b = [...document.querySelectorAll('.lib-menu button')].find(x => x.textContent.includes('跨資料夾')); const r = b.getBoundingClientRect(); return [r.left + 20, r.top + r.height / 2]; })()")
            await c.click(*pos); await asyncio.sleep(0.6)
            m = await sent(c, "lib_play")
            check("6b 選\"跨資料夾循環\"：送出 lib_play，scope=folders，視窗關閉", m and m[-1]["scope"] == "folders" and m[-1]["when"] == "replace" and not await c.js("document.getElementById('libDialog').open"), m[-1:] if m else m)

            # 7. 加入歌單按鈕 / the add-to-playlist button on a card
            async with s.get(f"{DBG}/fill", params={"n": 12, "clear": 1}) as r: await r.read()     # 剛才的播放換掉了待播，重新放一批 / the play above replaced the queue; put a batch back
            await asyncio.sleep(1.0)
            await click(c, "#queue .card:nth-of-type(5) .actions button:nth-child(1)", 0.8)
            check("7a 卡片的\"加入歌單\"：跳出選歌單的視窗，列出歌單與\"新歌單\"", await c.js("document.getElementById('pickDialog').open") and await count(c, "#pickList button") >= 2, await text(c, "#pickList"))
            await click(c, "#pickList button:nth-child(2)", 0.6)
            m = await sent(c, "lib_add")
            check("7b 選一張歌單：送出 lib_add，帶那首歌的 id", m and len(m[-1]["ids"]) == 1 and m[-1]["playlist"], m[-1:] if m else m)

            # 7c. Spotify（用假的 Spotify 回應）/ Spotify (with fake Spotify answers)
            await c.call("Page.navigate", url=f"{BASE}/g/{GID}"); await asyncio.sleep(1.5)
            check("7c Spotify 按鈕在 Bilibili 按鈕上方，一開始寫尚未連結", await c.js("(() => { const s = document.getElementById('spBtn'), b = document.getElementById('biliBtn'); return !s.hidden && s.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING; })()") and "尚未連結" in await text(c, "#spSub"), await text(c, "#spSub"))
            await click(c, "#btnLibrary", 0.8)
            check("7d 還沒連結時，歌單視窗裡沒有 Spotify 歌單的入口", not any("Spotify" in x for x in await c.js("[...document.querySelectorAll('#libBar button')].map(b => b.textContent)")))
            await c.js("document.getElementById('libDialog').close()")
            await click(c, "#spBtn", 0.5)
            check("7e 按 Spotify 按鈕：開授權視窗，說明裡有 redirect 網址", await c.js("document.getElementById('spDialog').open") and "127.0.0.1" in await text(c, "#spHow"), await text(c, "#spHow"))
            await click(c, "#spGo", 0.8)
            opened = await c.js("window.__opened")
            state = opened and opened[-1].split("state=")[1].split("&")[0]
            check("7f 前往授權：開出 Spotify 授權網址（帶 PKCE）", opened and opened[-1].startswith("https://accounts.spotify.com/authorize?") and "code_challenge=" in opened[-1], opened)
            await c.js("document.getElementById('spPaste').focus()")
            await c.type(f"http://127.0.0.1:8765/spotify/callback?code=ABC&state={state}")
            await click(c, "#spDone", 1.0)
            check("7g 貼回網址：連結成功，按鈕顯示 Spotify 暱稱", "測試帳號" in await text(c, "#spSub") and await c.js("!document.getElementById('spLinked').hidden"), await text(c, "#spSub"))
            await click(c, "#spOpenLists", 1.2)
            check("7h 開自己的 Spotify 歌單：歌單視窗出現 Spotify 歌單卡片", await c.js("document.getElementById('libDialog').open") and await count(c, ".sp-card") == 1 and "Spotify 最愛" in await text(c, ".sp-card .lib-name"), await text(c, "#libBody"))
            await click(c, ".sp-card", 1.0)
            m = await sent(c, "sp_import")
            check("7i 點一張：送出 sp_import，匯入後歌單視窗回到資料夾並有這張歌單", m and m[-1]["id"] == "p1", m[-1:] if m else m)
            await click(c, "#libUp", 0.6)
            check("7j 匯入的歌單出現在我的歌單裡（3 首）", any("Spotify 最愛" in x for x in await c.js("[...document.querySelectorAll('.lib-card .lib-name')].map(e => e.textContent)")), await text(c, "#libBody"))
            await c.js("document.getElementById('libDialog').close()")
            await click(c, "#spBtn", 0.4)
            await click(c, "#spLogout", 0.8)
            check("7k 登出：回到尚未連結", "尚未連結" in await text(c, "#spSub") and await c.js("!document.getElementById('spUnlinked').hidden"), await text(c, "#spSub"))
            await c.js("document.getElementById('spDialog').close()")

            # 8. 語言與手機寬度 / languages and a phone width
            await c.js("localStorage.setItem('mb_lang', 'en')")
            await c.call("Page.navigate", url=f"{BASE}/g/{GID}"); await asyncio.sleep(1.5)
            check("8a 英文：歌單按鈕提示是 My playlists", await c.js("document.getElementById('btnLibrary').title") == "My playlists", await c.js("document.getElementById('btnLibrary').title"))
            await click(c, "#btnLibrary", 0.8)
            check("8b 英文：視窗標題與麵包屑翻譯了", await text(c, "#libTitle") == "My playlists" and "My playlists" in await text(c, "#libCrumbs"), await text(c, "#libCrumbs"))
            await c.js("document.getElementById('libDialog').close(); localStorage.setItem('mb_lang', 'ja')")
            await c.call("Page.navigate", url=f"{BASE}/g/{GID}"); await asyncio.sleep(1.5)
            check("8c 日文：歌單按鈕提示是マイプレイリスト", await c.js("document.getElementById('btnLibrary').title") == "マイプレイリスト")
            await c.js("localStorage.setItem('mb_lang', 'zh-CN')")
            await c.call("Page.navigate", url=f"{BASE}/g/{GID}"); await asyncio.sleep(1.5)
            check("8d 簡體中文：歌單按鈕提示是我的歌单", await c.js("document.getElementById('btnLibrary').title") == "我的歌单")
            await c.js("localStorage.setItem('mb_lang', 'zh-TW')")
            await c.call("Emulation.setDeviceMetricsOverride", width=390, height=800, deviceScaleFactor=1, mobile=True)
            await c.call("Page.navigate", url=f"{BASE}/g/{GID}"); await asyncio.sleep(1.5)
            await click(c, "#btnLibrary", 0.8)
            box = await c.js("(() => { const r = document.getElementById('libBox').getBoundingClientRect(); return [Math.round(r.left), Math.round(r.right), innerWidth, document.documentElement.scrollWidth]; })()")
            check("8e 手機寬度：歌單視窗在畫面內，頁面不會左右捲", box[0] >= 0 and box[1] <= box[2] and box[3] <= box[2], box)
            errors = await c.js("window.__errs || []")
            check("8f 整個過程沒有 JS 錯誤", not errors, errors)
    print(f"\n總結：{sum(res)}/{len(res)} 通過")
asyncio.run(asyncio.wait_for(main(), 240))
