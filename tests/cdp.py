"""測試用的無頭 Chrome／Edge：用 DevTools Protocol 開頁面、執行 JS、送真正的滑鼠與鍵盤事件
Headless Chrome / Edge for the tests: open pages, run JS and send real mouse and keyboard events over the DevTools Protocol

perf_ui.py（效能）與 library_ui.py（歌單介面）共用 / shared by perf_ui.py (performance) and library_ui.py (library screens)
"""
import asyncio, json, os, shutil, subprocess, tempfile
import aiohttp

PORT = 9333


def find_browser():
    for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
        if os.path.exists(p): return p
    return shutil.which("chrome") or shutil.which("msedge")

class CDP:
    """最小的 DevTools Protocol 客戶端 / A minimal DevTools Protocol client."""
    def __init__(self, ws): self.ws, self.n = ws, 0
    async def call(self, method, **params):
        self.n += 1; i = self.n
        await self.ws.send_str(json.dumps({"id": i, "method": method, "params": params}))
        while True:
            m = json.loads((await self.ws.receive()).data)
            if m.get("id") == i:
                if "error" in m: raise RuntimeError(f"{method}: {m['error']}")
                return m.get("result", {})
    async def js(self, code):
        r = await self.call("Runtime.evaluate", expression=code, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in r: raise RuntimeError(str(r["exceptionDetails"])[:300])
        return r["result"].get("value")
    async def mouse(self, kind, x, y, **kw): await self.call("Input.dispatchMouseEvent", type=kind, x=x, y=y, button="left", clickCount=1, **kw)
    async def click(self, x, y):
        await self.mouse("mouseMoved", x, y); await self.mouse("mousePressed", x, y); await self.mouse("mouseReleased", x, y)
    async def type(self, text): await self.call("Input.insertText", text=text)
    async def key(self, key, code=None):
        for kind in ("keyDown", "keyUp"): await self.call("Input.dispatchKeyEvent", type=kind, key=key, code=code or key, windowsVirtualKeyCode={"Enter": 13, "Escape": 27}.get(key, 0))
    async def wheel(self, x, y, dy): await self.call("Input.dispatchMouseEvent", type="mouseWheel", x=x, y=y, deltaX=0, deltaY=dy)



class Browser:
    """啟動無頭瀏覽器並接上第一個分頁；用 async with / Start a headless browser and attach to a tab; use ``async with``."""
    def __init__(self, session, size="1400,900"):
        self.s, self.size, self.proc, self.c, self.prof = session, size, None, None, None

    async def __aenter__(self):
        exe = find_browser()
        if not exe: return None
        self.prof = tempfile.mkdtemp(prefix="cdp_", dir=os.environ.get("PERF_TMP") or None)     # 瀏覽器暫存資料夾；預設用系統暫存，可用環境變數 PERF_TMP 改位置 / the browser profile folder; the system temp by default, PERF_TMP changes it
        self.proc = subprocess.Popen([exe, "--headless=new", f"--remote-debugging-port={PORT}", f"--user-data-dir={self.prof}", "--no-first-run",
                                      "--disable-extensions", f"--window-size={self.size}", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            await asyncio.sleep(0.25)
            try:
                async with self.s.put(f"http://127.0.0.1:{PORT}/json/new?about:blank") as r: tab = await r.json()
                ws = await self.s.ws_connect(tab["webSocketDebuggerUrl"], max_msg_size=0)
                self.c = CDP(ws)
                await self.c.call("Page.enable"); await self.c.call("Runtime.enable")
                return self.c
            except Exception: pass
        return None

    async def __aexit__(self, *exc):
        if self.proc:
            self.proc.terminate()
            try: self.proc.wait(10)
            except Exception: self.proc.kill()
        if self.prof: shutil.rmtree(self.prof, ignore_errors=True)
