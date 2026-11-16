"""桌面控制面板的測試：找專案、解析外部程序、啟動／停止（用假的 bot.py，不碰真的機器人）、配色、視窗狀態
Tests of the desktop control panel: finding the project, parsing external processes, start / stop (a fake bot.py, the real bot is never touched), colours, window states

只在 Windows 且有畫面時跑視窗那幾項，其他環境會略過 / the window checks only run on Windows with a display, otherwise they are skipped
用 tests/run_all.py 執行 / run it with tests/run_all.py
"""
import json
import os
import queue
import sys
import tempfile
import time
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 專案根目錄 / project root
sys.path.insert(0, os.path.join(ROOT, "launcher"))

res = []
def check(n, ok, d=""): res.append(bool(ok)); print(("PASS" if ok else "FAIL"), n, str(d)[:190], flush=True)

if os.name != "nt":
    print("略過：不是 Windows / skipped: not Windows")
    print("0/0 通過")
    sys.exit(0)

from botpanel import paths, theme
from botpanel.procs import BotRunner, parse_external

tmp = Path(tempfile.mkdtemp(prefix="launcher_test_"))
proj = tmp / "proj"
proj.mkdir()
(proj / "bot.py").write_text(
    "import sys, time\n"
    "mode = sys.argv[1] if len(sys.argv) > 1 else 'stay'\n"
    "print('已登入：測試機器人', flush=True)\n"
    "if mode == 'crash':\n"
    "    print('ERROR boom', flush=True); sys.exit(3)\n"
    "for i in range(600):\n"
    "    print('tick', i, flush=True); time.sleep(0.2)\n", encoding="utf-8")

# ============ 路徑 ============
os.environ["MUSICBOT_DIR"] = str(proj)
check("L1 MUSICBOT_DIR 指到含 bot.py 的資料夾就用它", paths.find_project() == proj, paths.find_project())
os.environ["MUSICBOT_DIR"] = str(tmp)   # 沒有 bot.py
os.environ["APPDATA"] = str(tmp / "appdata")
paths.remember_project(proj)
cfg = json.loads((tmp / "appdata" / "MusicBotLauncher" / "launcher.json").read_text(encoding="utf-8"))
check("L2 記住的專案位置存進 %APPDATA%", cfg["project"] == str(proj), cfg)
found = paths.find_project()
check("L3 環境變數沒用時，改用記住的位置", found == proj, found)
(proj / ".env").write_text("RELAY_URL=wss://example.com/relay\n", encoding="utf-8")
check("L4 看板網址由 RELAY_URL 推出（wss -> https）", paths.dashboard_url(proj) == "https://example.com/relay", paths.dashboard_url(proj))
(proj / ".env").write_text("OTHER=1\n", encoding="utf-8")
check("L5 沒有 RELAY_URL 就用本機網址", paths.dashboard_url(proj) == "http://127.0.0.1:8765")

# ============ 外部程序 ============
out = f"100|{proj}\\.venv\\Scripts\\python.exe\n200|C:\\other\\.venv\\Scripts\\python.exe\nabc|{proj}\\.venv\\x\n300|{str(proj).upper()}\\.VENV\\Scripts\\python.exe\n"
check("P1 只認這個專案 .venv 的程序（不分大小寫、略過壞行）", parse_external(out, proj) == [100, 300], parse_external(out, proj))

# ============ 啟動／停止（假的 bot.py）============
q: "queue.Queue[str]" = queue.Queue()
r = BotRunner(proj, q)
r.python = lambda: Path(sys.executable)   # 不用專案的 .venv / use this interpreter instead of the project's .venv
r.start()
time.sleep(1.5)
lines = []
while not q.empty(): lines.append(q.get())
check("R1 啟動後讀得到機器人的輸出", any("已登入：測試機器人" in l for l in lines) and any("tick" in l for l in lines), lines[:3])
check("R2 running() 為真，finished() 為 None", r.running() and r.finished() is None)
r.stop()
check("R3 stop() 結束程序", not r.running() and r.proc is None)

r2 = BotRunner(proj, q)
r2.python = lambda: Path(sys.executable)
import subprocess
r2.proc = subprocess.Popen([sys.executable, str(proj / "bot.py"), "crash"], cwd=str(proj), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
time.sleep(1.5)
check("R4 自己結束時 finished() 回傳結束代碼", r2.finished() == 3 and r2.proc is None)

# ============ 配色 ============
check("T1 lerp 兩端", theme.lerp("#000000", "#ffffff", 0) == "#000000" and theme.lerp("#000000", "#ffffff", 1) == "#ffffff" and theme.lerp("#000000", "#ffffff", 0.5) == "#808080")
check("T2 背景漸層頭尾同看板", theme.bg_at(0) == "#AFA3CB".lower() and theme.bg_at(1) == "#F7E0D3".lower(), (theme.bg_at(0), theme.bg_at(1)))
check("T3 glass 疊白色，alpha 越大越白", theme.glass("#000000", 0.5) == "#808080" and theme.glass("#336699", 0.9) > theme.glass("#336699", 0.2))

# ============ 視窗 ============
try:
    import tkinter as tk
    root = tk.Tk()
except Exception as exc:   # 沒有畫面 / no display
    print("略過視窗：", exc)
    print(f"{sum(res)}/{len(res)} 通過")
    sys.exit(0 if all(res) else 1)

from botpanel.window import App

def drain(app, ms):
    end = time.time() + ms / 1000
    while time.time() < end:
        root.update(); time.sleep(0.02)

root.geometry("820x560+60+60")
app = App(root, proj)
app.runner.python = lambda: Path(sys.executable)
real_popen = subprocess.Popen
check("W1 開啟時是已停止，按鈕狀態正確", app.kind == "stopped" and app.b_start.enabled and not app.b_stop.enabled and not app.b_restart.enabled)
drain(app, 300)
check("W2 六顆按鈕都畫出來了", all(app.cv.find_withtag(b.tag) for b in (*app.controls, *app.tools)))

# 用假 bot.py：把啟動指令換成 `python bot.py`（stay）
app.start(); drain(app, 2500)
txt = app.log.get("1.0", "end")
check("W3 按啟動 -> 執行中，紀錄出現輸出", app.kind == "running" and "已登入：測試機器人" in txt, (app.kind, txt[-80:]))
check("W4 執行中：啟動停用、停止和重新啟動可按", not app.b_start.enabled and app.b_stop.enabled and app.b_restart.enabled)
ok_tags = app.log.tag_ranges("ok")
check("W5 「已登入」那行用綠色標記", len(ok_tags) >= 2, ok_tags)
app.stop(); drain(app, 3000)
check("W6 按停止 -> 已停止", app.kind == "stopped" and not app.running(), app.kind)
app.runner.proc = real_popen([sys.executable, str(proj / "bot.py"), "crash"], cwd=str(proj), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
drain(app, 3200)
check("W7 機器人自己掛掉 -> 異常結束並顯示代碼", app.kind == "crashed" and "3" in app.detail, (app.kind, app.detail))
check("W8 錯誤行用紅色標記", len(app.log.tag_ranges("err")) >= 2, app.log.tag_ranges("err"))
app.clear_log()
check("W9 清除紀錄", app.log.get("1.0", "end").strip() == "")
root.geometry("740x440+60+60"); drain(app, 400)
check("W10 縮到最小也畫得出來（不出錯）", app.cv.winfo_width() >= 700)
app.runner.kill_own()
root.destroy()

print(f"{sum(res)}/{len(res)} 通過", flush=True)
sys.exit(0 if all(res) else 1)
