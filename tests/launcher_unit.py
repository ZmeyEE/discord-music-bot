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
os.environ["LOCALAPPDATA"] = str(tmp / "localappdata")   # 測試不能動到真的 instance.json / the tests must not touch the real instance.json
paths.remember_project(proj)
cfg = json.loads((tmp / "appdata" / "MusicBotLauncher" / "launcher.json").read_text(encoding="utf-8"))
check("L2 記住的專案位置存進 %APPDATA%", cfg["project"] == str(proj), cfg)
found = paths.find_project()
check("L3 環境變數沒用時，改用記住的位置", found == proj, found)
(proj / ".env").write_text("RELAY_URL=wss://example.com/relay\n", encoding="utf-8")
check("L4 看板網址由 RELAY_URL 推出（wss -> https）", paths.dashboard_url(proj) == "https://example.com/relay", paths.dashboard_url(proj))
(proj / ".env").write_text("OTHER=1\n", encoding="utf-8")
check("L5 沒有 RELAY_URL 就用本機網址", paths.dashboard_url(proj) == "http://127.0.0.1:8765")
side = tmp / "side"
(side / "panel").mkdir(parents=True)
(side / "bot1").mkdir(); (side / "bot1" / "bot.py").write_text("", encoding="utf-8"); (side / "bot1" / "musicbot").mkdir()
(side / "notbot").mkdir(); (side / "notbot" / "bot.py").write_text("", encoding="utf-8")   # 有 bot.py 但沒有 musicbot/ / bot.py but no musicbot/
check("L6 exe 放在專案隔壁：認得隔壁那個有 bot.py 和 musicbot/ 的資料夾", paths.sibling_projects(side) == [str(side / "bot1")], paths.sibling_projects(side))
(side / "bot2").mkdir(); (side / "bot2" / "bot.py").write_text("", encoding="utf-8"); (side / "bot2" / "musicbot").mkdir()
check("L7 隔壁有兩個符合的就不猜（回傳空）", paths.sibling_projects(side) == [])

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

# ============ 重複開啟 ============
import subprocess
from botpanel import procs
TEST_MUTEX = "Local\\DiscordMusicBotLauncherTest%d" % os.getpid()   # 測試用的名字，不會碰到真的控制面板 / a test-only name, never collides with a real panel
procs.MUTEX_NAME = TEST_MUTEX
probe = [sys.executable, "-X", "utf8", "-c",
         "import sys; sys.path.insert(0, sys.argv[1]); from botpanel import procs; procs.MUTEX_NAME = sys.argv[2]; print(procs.single_instance())",
         os.path.join(ROOT, "launcher"), TEST_MUTEX]
check("D1 第一個搶到互斥鎖", procs.single_instance() is True)
second = subprocess.run(probe, capture_output=True, text=True, timeout=30).stdout.strip()
check("D2 另一個程序搶不到（回傳 False）", second == "False", second)
procs.release_instance()
third = subprocess.run(probe, capture_output=True, text=True, timeout=30).stdout.strip()
check("D3 放開後，別的程序就搶得到（搶輸時沒有留下控制代碼卡住它）", third == "True", third)
procs.single_instance()   # 我們先搶到 / we take it first
LOSER = ("import sys, time; sys.path.insert(0, sys.argv[1]); from botpanel import procs; procs.MUTEX_NAME = sys.argv[2];"
         " print(procs.single_instance(), flush=True); time.sleep(8)")
loser = subprocess.Popen([sys.executable, "-X", "utf8", "-c", LOSER, os.path.join(ROOT, "launcher"), TEST_MUTEX], stdout=subprocess.PIPE, text=True)
loser_said = loser.stdout.readline().strip()
procs.release_instance()                  # 舊的控制面板結束了 / the old panel is gone
fourth = subprocess.run(probe, capture_output=True, text=True, timeout=30).stdout.strip()
loser.kill()
check("D6 搶輸的程序還活著，也不會害別人搶不到（舊版的漏洞：「已經開著」的提示視窗自己卡住了互斥鎖）", loser_said == "False" and fourth == "True", (loser_said, fourth))
procs.single_instance()   # 搶到鎖並記下自己的程序代號 / take the lock, which records our process id
OTHER = ("import sys; sys.path.insert(0, sys.argv[1]); from botpanel import procs; print(*procs.other_panels())")
# 中間隔一層 cmd，這樣我們不是它的父程序（other_panels 會略過自己的父程序）/ one cmd in between so we are not its parent (other_panels skips the caller's parent)
seen = subprocess.run(["cmd", "/c", sys.executable, "-X", "utf8", "-c", OTHER, os.path.join(ROOT, "launcher")], capture_output=True, text=True, timeout=60).stdout.split()
check("D7 另一次啟動靠記錄的程序代號找得到我（不管 exe 叫什麼名字）", str(os.getpid()) in seen, seen)
procs.release_instance()
check("D4 找不到的視窗標題回傳 False", procs.focus_existing("沒有這個視窗 launcher-test-xyz") is False)
check("D5 other_panels 不會把自己算進去", os.getpid() not in procs.other_panels())

# ============ 版本與打包 ============
import re
import importlib.util
import botpanel
spec = importlib.util.spec_from_file_location("launcher_build", os.path.join(ROOT, "launcher", "build.py"))
build = importlib.util.module_from_spec(spec); spec.loader.exec_module(build)
check("V1 版本號是 x.y.z", re.fullmatch(r"\d+\.\d+\.\d+", botpanel.__version__) is not None, botpanel.__version__)
check("V2 Windows 版本四個數字（1.1.0 -> 1,1,0,0）", build.numbers("1.1.0") == (1, 1, 0, 0) and build.numbers("2.10") == (2, 10, 0, 0), build.numbers("1.1.0"))
vi = build.version_info("1.1.0")
check("V3 版本資訊檔含檔案版本、產品版本和帶版本的原始檔名", "'FileVersion', '" + ".".join(["1", "1", "0", "0"]) + "'" in vi and "'ProductVersion', '1.1.0'" in vi and "MusicBotLauncher-1.1.0.exe" in vi)
musicbot_ver = re.search(r'__version__ = "([^"]+)"', open(os.path.join(ROOT, "musicbot", "__init__.py"), encoding="utf-8").read()).group(1)
check("V4 控制面板版本和 musicbot 版本一致（改版時要一起改）", botpanel.__version__ == musicbot_ver, (botpanel.__version__, musicbot_ver))

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

# 滑鼠：按鈕用座標判斷，不綁在圖形上（舊版游標停在按鈕上會無限重畫、視窗變"沒有回應"）
# Mouse: buttons are hit-tested by coordinates, not bound to items (the old version redrew endlessly under a resting pointer and the window froze)
from botpanel import widgets
draws = [0]
real_draw = widgets.Pill.draw
widgets.Pill.draw = lambda self: (draws.__setitem__(0, draws[0] + 1), real_draw(self))[1]
btn = app.b_open
bx0, by0, bx1, by1 = btn.box
cx, cy = int((bx0 + bx1) / 2), int((by0 + by1) / 2)
clicked = []
btn.command = lambda: clicked.append(1)
drain(app, 300); before = draws[0]
app.cv.event_generate("<Motion>", x=cx, y=cy); drain(app, 600)
check("H1 滑鼠移到按鈕上：只重畫一次，不會一直重畫", btn._hover and app.pills.hover is btn and draws[0] - before <= 2, draws[0] - before)
before = draws[0]; drain(app, 1500)
check("H2 游標停著不動：完全不重畫（舊版在這裡無限迴圈）", draws[0] == before, draws[0] - before)
app.cv.event_generate("<ButtonPress-1>", x=cx, y=cy); app.cv.event_generate("<ButtonRelease-1>", x=cx, y=cy); drain(app, 200)
check("H3 在按鈕上按下再放開：執行一次動作", clicked == [1], clicked)
app.cv.event_generate("<ButtonPress-1>", x=cx, y=cy); app.cv.event_generate("<ButtonRelease-1>", x=5, y=5); drain(app, 200)
check("H4 按下後移到外面才放開：不執行", clicked == [1], clicked)
app.cv.event_generate("<Motion>", x=5, y=5); drain(app, 300)
check("H5 移開後恢復原樣", not btn._hover and app.pills.hover is None)
app.cv.event_generate("<Leave>"); drain(app, 100)
widgets.Pill.draw = real_draw

# 關視窗時，外部啟動的機器人要先問 / closing the window asks about a bot started elsewhere
from tkinter import messagebox as mb
answers, stopped = [None], []
mb.askyesnocancel = lambda *a, **k: answers[0]
app.kind, app.runner.proc = "running", None
app.runner.stop = lambda: stopped.append(1)
app.on_close()
check("W11 外部啟動的機器人：關視窗會先問，取消就不關", root.winfo_exists() and not stopped)
FOCUS_TITLE = "launcher-focus-test-%d" % os.getpid()   # 每次執行不同，同時跑好幾份也不會找到別人的視窗 / unique per run, so concurrent runs never find each other's window
root.title(FOCUS_TITLE)
root.iconify(); drain(app, 300)
focused = procs.focus_existing(FOCUS_TITLE)
drain(app, 300)
check("W12 縮小的視窗被叫回前面", focused is True and root.state() == "normal", root.state())
root.title("Discord 音樂機器人")
answers[0] = True
t_end = time.time() + 5
app.on_close()
t_call = time.time()
check("W13 選「是」：停止在背景做，on_close 馬上回來（不卡住視窗）", t_call - (t_end - 5) < 0.5, round(t_call - (t_end - 5), 2))
closed = False
while time.time() < t_end:
    try:
        root.update()
        root.winfo_exists()   # 視窗關掉後 update() 不會報錯，但這個會 / after the window is gone update() stays quiet but this raises
    except tk.TclError:
        closed = True
        break
    time.sleep(0.02)
check("W14 背景停止完成後視窗才關閉", stopped == [1] and closed, (stopped, closed))
sys.stdout.flush()

print(f"{sum(res)}/{len(res)} 通過", flush=True)
sys.exit(0 if all(res) else 1)
