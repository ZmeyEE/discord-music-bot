"""機器人控制面板：用按鈕啟動／停止 Discord 音樂機器人，並顯示即時紀錄

只是"遙控器"：真正的機器人仍是專案裡的 bot.py（由 .venv 的 Python 執行）

專案資料夾位置依序從這些地方找（找到第一個含 bot.py 的就用）：
  1. 環境變數 MUSICBOT_DIR
  2. launcher.json（放在 exe 旁邊，或 %APPDATA%\\MusicBotLauncher\\）：{"project": "專案資料夾路徑"}
  3. 以原始碼執行時：launcher/ 的上一層；打包成 exe 時：exe 所在資料夾或它的上一層
  4. 都找不到 -> 跳出視窗請你選擇資料夾，並記住（寫進 %APPDATA%\\MusicBotLauncher\\launcher.json）

Bot control panel: start / stop the Discord music bot with buttons and watch the live log.

It is only a "remote control": the real bot is still ``bot.py`` in the project (run with the .venv's Python).

The project folder is searched in this order (the first one containing bot.py wins):
  1. the ``MUSICBOT_DIR`` environment variable
  2. ``launcher.json`` (next to the exe, or in ``%APPDATA%\\MusicBotLauncher\\``): {"project": "path to the project"}
  3. running from source: the parent of ``launcher/``; packaged exe: the exe's folder or its parent
  4. nothing found -> a folder picker asks you, and the answer is remembered
     (saved to ``%APPDATA%\\MusicBotLauncher\\launcher.json``)

Build the exe / 打包成 exe:
  pip install pyinstaller
  pyinstaller --onefile --windowed --name MusicBotLauncher launcher/launcher.py
"""
from __future__ import annotations

import ctypes
import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

APP_TITLE = "Discord 音樂機器人"
MUTEX_NAME = "Local\\DiscordMusicBotLauncher"   # 單一實例用的 Windows 互斥鎖名稱 / Windows mutex name for the single-instance guard
MAX_LOG_LINES = 800                              # 視窗裡最多保留幾行紀錄 / how many log lines the window keeps
NO_WINDOW = 0x08000000                           # CREATE_NO_WINDOW：子程序不要跳出黑色視窗 / CREATE_NO_WINDOW: no console window for child processes

# 狀態燈顏色 / status-light colours
GREEN, RED, GRAY, AMBER = "#2e9e5b", "#d64545", "#8a8f98", "#d99a22"


# ============================================================
# 小工具 / Helpers
# ============================================================
def app_dir() -> Path:
    """這個程式所在的資料夾（exe 或 .py 旁邊） / The folder this program lives in (next to the exe or the .py)."""
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent


def user_config_path() -> Path:
    """記住專案位置的設定檔（每個 Windows 使用者各自一份） / The config file that remembers the project location (one per Windows user)."""
    return Path(os.environ.get("APPDATA") or Path.home()) / "MusicBotLauncher" / "launcher.json"


def find_project() -> Path | None:
    """依上面的順序找專案資料夾；找不到回傳 None

    Look for the project folder in the order described at the top; returns None if not found.
    """
    cands: list[str] = [os.environ.get("MUSICBOT_DIR", "")]
    for cfg in (app_dir() / "launcher.json", user_config_path()):
        if cfg.exists():
            try:
                cands.append(json.loads(cfg.read_text(encoding="utf-8-sig")).get("project", ""))
            except (OSError, ValueError):
                pass
    if getattr(sys, "frozen", False):
        cands += [str(app_dir()), str(app_dir().parent)]
    else:
        cands.append(str(app_dir().parent))
    for c in cands:
        if c and (Path(c) / "bot.py").exists():
            return Path(c)
    return None


def remember_project(project: Path) -> None:
    """把使用者選的專案資料夾存起來，下次不用再選 / Save the folder the user picked so we don't ask again."""
    path = user_config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"project": str(project)}, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def ask_project() -> Path | None:
    """跳出資料夾選擇視窗，直到選到含 bot.py 的資料夾或使用者取消

    Show a folder picker until the user chooses a folder containing bot.py, or cancels.
    """
    while True:
        picked = filedialog.askdirectory(title="請選擇機器人專案資料夾（裡面要有 bot.py）/ Select the bot project folder (must contain bot.py)")
        if not picked:
            return None
        if (Path(picked) / "bot.py").exists():
            remember_project(Path(picked))
            return Path(picked)
        messagebox.showerror(APP_TITLE, "這個資料夾裡沒有 bot.py，請再選一次。\nNo bot.py in that folder, please try again.")


def dashboard_url(project: Path) -> str:
    """從 .env 的 RELAY_URL 推出看板網址（ws:// → http://）；沒有就用本地

    Work out the dashboard URL from ``RELAY_URL`` in .env (ws:// -> http://); falls back to localhost.
    """
    try:
        for line in (project / ".env").read_text(encoding="utf-8-sig").splitlines():
            if line.startswith("RELAY_URL="):
                u = line.split("=", 1)[1].strip().strip("\"'")
                if u:
                    return u.replace("wss://", "https://", 1).replace("ws://", "http://", 1)
    except OSError:
        pass
    return "http://127.0.0.1:8765"


def single_instance() -> bool:
    """同一時間只允許一個控制面板，避免不小心開出兩個機器人

    Allow only one control panel at a time so you can't accidentally start two bots.
    """
    h = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    ERROR_ALREADY_EXISTS = 183
    return bool(h) and ctypes.windll.kernel32.GetLastError() != ERROR_ALREADY_EXISTS


def run_hidden(args: list[str], timeout: int = 15) -> str:
    """執行外部指令（不跳視窗）並回傳輸出文字；失敗回傳空字串

    Run an external command without a console window and return its output; returns "" on failure.
    """
    try:
        r = subprocess.run(args, capture_output=True, timeout=timeout, creationflags=NO_WINDOW)
        return r.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return ""


def find_external_bots(project: Path) -> list[int]:
    """找出不是本程式開的、正在跑同一個專案 bot.py 的 Python 程序

    Find Python processes that run this project's bot.py but were not started by this panel
    (for example launched through start.bat).
    """
    ps = (
        "$p = Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Where-Object { $_.CommandLine -like '*bot.py*' }; "
        "$p | ForEach-Object { $_.ProcessId.ToString() + '|' + $_.ExecutablePath }"
    )
    out = run_hidden(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps])
    # 只認"這個專案的 .venv 的 python"，不會誤殺別的 bot.py
    # Only the python of THIS project's .venv counts, so some other bot.py is never killed by mistake.
    key = str(project / ".venv").lower()
    pids: list[int] = []
    for line in out.splitlines():
        pid, _, exe = line.partition("|")
        if pid.strip().isdigit() and exe.strip().lower().startswith(key):
            pids.append(int(pid))
    return pids


def kill_tree(pid: int) -> None:
    """結束一個程序與它底下所有子程序（/T） / Kill a process together with all of its children (/T)."""
    run_hidden(["taskkill", "/PID", str(pid), "/T", "/F"], timeout=20)


# ============================================================
# 視窗本體 / The window
# ============================================================
class App:
    """控制面板視窗：狀態燈、三個控制按鈕、即時紀錄

    The control-panel window: a status light, three control buttons and a live log.
    UI work stays on the main thread; slow work (starting/stopping/scanning) runs in helper threads and
    reports back with ``root.after``.
    """

    def __init__(self, root: tk.Tk, project: Path) -> None:
        self.root = root
        self.project = project
        self.url = dashboard_url(self.project)
        self.proc: subprocess.Popen | None = None
        self.lines: queue.Queue[str] = queue.Queue()   # 背景執行緒把機器人輸出丟進來，主執行緒再顯示 / helper threads drop the bot's output here; the main thread displays it
        self.busy = False  # 啟動／停止進行中，避免連點 / a start/stop is in progress; prevents double clicks

        root.title(APP_TITLE)
        root.geometry("720x520")
        root.minsize(560, 380)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        # --- 上方：狀態燈 / top: status light ---
        top = ttk.Frame(root, padding=(14, 12, 14, 6))
        top.pack(fill="x")
        self.dot = tk.Canvas(top, width=22, height=22, highlightthickness=0, bd=0)
        self.dot.pack(side="left")
        self.light = self.dot.create_oval(3, 3, 19, 19, fill=GRAY, outline="")
        self.status = ttk.Label(top, text="已停止", font=("Microsoft JhengHei UI", 15, "bold"))
        self.status.pack(side="left", padx=(8, 0))
        self.detail = ttk.Label(top, text="", foreground=GRAY)
        self.detail.pack(side="left", padx=(12, 0))

        # --- 中間：按鈕列 / middle: button bar ---
        bar = ttk.Frame(root, padding=(14, 4, 14, 8))
        bar.pack(fill="x")
        self.b_start = ttk.Button(bar, text="▶ 啟動", width=10, command=self.start)
        self.b_stop = ttk.Button(bar, text="■ 停止", width=10, command=self.stop)
        self.b_restart = ttk.Button(bar, text="↻ 重新啟動", width=12, command=self.restart)
        for b in (self.b_start, self.b_stop, self.b_restart):
            b.pack(side="left", padx=(0, 8))
        ttk.Button(bar, text="開啟看板", command=lambda: webbrowser.open(self.url)).pack(side="right")
        ttk.Button(bar, text="專案資料夾", command=self.open_folder).pack(side="right", padx=(0, 8))
        ttk.Button(bar, text="清除紀錄", command=self.clear_log).pack(side="right", padx=(0, 8))

        # --- 下方：紀錄視窗 / bottom: log view ---
        wrap = ttk.Frame(root, padding=(14, 0, 14, 12))
        wrap.pack(fill="both", expand=True)
        self.log = tk.Text(
            wrap, wrap="none", state="disabled", font=("Consolas", 10), bg="#14161a", fg="#d7dae0",
            insertbackground="#d7dae0", relief="flat", padx=8, pady=6,
        )
        sy = ttk.Scrollbar(wrap, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=sy.set)
        sy.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        self.log.tag_configure("err", foreground="#ff7b72")
        self.log.tag_configure("ok", foreground="#7ee787")
        self.log.tag_configure("sys", foreground="#79c0ff")

        self.say(f"專案 / Project：{self.project}", "sys")
        self.set_state("stopped")
        self.pump()
        self.poll()
        root.after(400, self.check_external_on_open)

    # ------------------------------------------------------------
    # 紀錄 / Logging
    # ------------------------------------------------------------
    def say(self, text: str, tag: str = "") -> None:
        """在紀錄視窗加一行，超過上限就刪掉最舊的 / Append a line to the log view; the oldest lines are dropped past the limit."""
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip("\n") + "\n", tag)
        extra = int(self.log.index("end-1c").split(".")[0]) - MAX_LOG_LINES
        if extra > 0:
            self.log.delete("1.0", f"{extra + 1}.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def clear_log(self) -> None:
        """清除紀錄視窗 / Clear the log view."""
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def pump(self) -> None:
        """每 0.1 秒把佇列裡的輸出搬到畫面上（一次最多 200 行，避免卡住介面）

        Every 0.1 s move queued output onto the screen (at most 200 lines per round so the UI stays responsive).
        """
        n = 0
        while n < 200:
            try:
                line = self.lines.get_nowait()
            except queue.Empty:
                break
            tag = "err" if any(k in line for k in ("ERROR", "Traceback", "CRITICAL")) else (
                "ok" if "已登入" in line or "已連上中繼站" in line else "")
            self.say(line, tag)
            n += 1
        self.root.after(100, self.pump)

    # ------------------------------------------------------------
    # 狀態 / State
    # ------------------------------------------------------------
    def running(self) -> bool:
        """本程式啟動的機器人是否還在跑 / Is the bot started by this panel still running?"""
        return self.proc is not None and self.proc.poll() is None

    def set_state(self, kind: str, detail: str = "") -> None:
        """更新狀態燈與按鈕可用性，kind：running / stopped / starting / stopping / crashed

        Update the status light and which buttons are enabled.
        ``kind`` is one of: running / stopped / starting / stopping / crashed.
        """
        look = {
            "running": ("執行中", GREEN), "stopped": ("已停止", GRAY),
            "starting": ("啟動中…", AMBER), "stopping": ("停止中…", AMBER), "crashed": ("異常結束", RED),
        }[kind]
        self.status.configure(text=look[0])
        self.dot.itemconfigure(self.light, fill=look[1])
        self.detail.configure(text=detail)
        idle = not self.busy
        on = kind in ("running", "starting")
        self.b_start.state(["!disabled"] if (idle and not on) else ["disabled"])
        self.b_stop.state(["!disabled"] if (idle and kind != "stopped") else ["disabled"])
        self.b_restart.state(["!disabled"] if (idle and kind in ("running", "crashed")) else ["disabled"])

    def poll(self) -> None:
        """每秒檢查機器人是否自己結束了（例如連線錯誤、被外部關掉）

        Once a second, check whether the bot ended by itself (a connection error, closed from outside...).
        """
        if self.proc is not None and not self.busy and self.proc.poll() is not None:
            code = self.proc.returncode
            self.proc = None
            if code == 0:
                self.say("機器人已結束。", "sys")
                self.set_state("stopped")
            else:
                self.say(f"機器人意外結束（代碼 {code}），請看上面的紀錄找原因。", "err")
                self.set_state("crashed", f"代碼 {code}")
        self.root.after(1000, self.poll)

    # ------------------------------------------------------------
    # 動作 / Actions
    # ------------------------------------------------------------
    def work(self, fn) -> None:
        """在背景執行緒做耗時的事，並鎖住按鈕避免連點 / Run slow work in a background thread and lock the buttons meanwhile."""
        self.busy = True
        threading.Thread(target=fn, daemon=True).start()

    def check_external_on_open(self) -> None:
        """開啟時掃描一次：有沒有別處啟動的機器人 / Scan once at start-up: is a bot already running from somewhere else?"""
        def go() -> None:
            pids = find_external_bots(self.project)
            self.root.after(0, lambda: self.after_scan_on_open(pids))
        threading.Thread(target=go, daemon=True).start()

    def after_scan_on_open(self, pids: list[int]) -> None:
        """掃描結果：若有外部機器人，提示並顯示為執行中（按"停止"可關掉它）

        Scan result: if an external bot exists, say so and show "running" (the Stop button can close it).
        """
        if pids and not self.running():
            self.say(f"偵測到已有機器人在執行（不是由本程式開的，程序 {pids}）。要關掉它，請按「停止」。", "sys")
            self.set_state("running", "外部啟動")

    def start(self) -> None:
        """按下"啟動" / The Start button."""
        if self.running() or self.busy:
            return
        py = self.project / ".venv" / "Scripts" / "python.exe"
        if not py.exists():
            messagebox.showerror(APP_TITLE, f"找不到 Python 環境：\n{py}\n\n請見 README 建立 .venv。\nPython environment not found - see the README to create the .venv.")
            return
        self.set_state("starting")
        self.work(lambda: self._start_worker(py))

    def _start_worker(self, py: Path) -> None:
        """（背景執行緒）關掉外部的舊機器人、啟動新的，並開始讀它的輸出

        (Background thread) close any external bot, start a new one and begin reading its output.
        """
        try:
            ext = find_external_bots(self.project)
            if ext:
                self.lines.put(f"[控制面板] 偵測到已有機器人在跑（{ext}），先關掉它避免重複登入…")
                for p in ext:
                    kill_tree(p)
            env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
            self.proc = subprocess.Popen(
                [str(py), "-X", "utf8", "-u", "bot.py"], cwd=str(self.project), env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                creationflags=NO_WINDOW,
            )
            threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()
            self.lines.put("[控制面板] 機器人啟動中…")
            self.root.after(0, lambda: self._done("running", "已啟動"))
        except OSError as e:
            self.lines.put(f"[控制面板] 啟動失敗：{e}")
            self.root.after(0, lambda: self._done("crashed", "啟動失敗"))

    def _reader(self, proc: subprocess.Popen) -> None:
        """（背景執行緒）一行一行讀機器人的輸出，丟進佇列 / (Background thread) read the bot's output line by line into the queue."""
        assert proc.stdout is not None
        for raw in iter(proc.stdout.readline, b""):
            self.lines.put(raw.decode("utf-8", "replace"))

    def _done(self, kind: str, detail: str = "") -> None:
        """背景工作做完：解鎖按鈕並更新狀態 / Background work finished: unlock the buttons and update the state."""
        self.busy = False
        self.set_state(kind, detail)

    def stop(self, then=None) -> None:
        """按下"停止"，``then`` 是停止完成後要接著做的事（重新啟動用）

        The Stop button. ``then`` is an optional follow-up to run once stopped (used by Restart).
        """
        if self.busy:
            return
        self.set_state("stopping")
        self.work(lambda: self._stop_worker(then))

    def _stop_worker(self, then) -> None:
        """（背景執行緒）結束自己啟動的機器人，也一併結束外部啟動的 / (Background thread) stop our own bot and any externally started one."""
        proc = self.proc
        if proc is not None and proc.poll() is None:
            kill_tree(proc.pid)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        self.proc = None
        for p in find_external_bots(self.project):
            kill_tree(p)
        self.lines.put("[控制面板] 機器人已停止。")
        self.root.after(0, lambda: (self._done("stopped"), then() if then else None))

    def restart(self) -> None:
        """按下"重新啟動"：先停止，停完再啟動 / The Restart button: stop first, then start."""
        self.stop(then=self.start)

    def open_folder(self) -> None:
        """用檔案總管開啟專案資料夾 / Open the project folder in Explorer."""
        try:
            os.startfile(str(self.project))  # type: ignore[attr-defined]
        except OSError as e:
            messagebox.showerror(APP_TITLE, str(e))

    def on_close(self) -> None:
        """關閉視窗：機器人還在跑就先確認，並一併停止它 / Closing the window: confirm if the bot is running, and stop it too."""
        if self.running() or self.busy:
            if not messagebox.askokcancel(APP_TITLE, "機器人還在執行。\n關閉視窗會一併停止機器人，確定要關閉嗎？\nThe bot is still running; closing the window stops it too. Continue?"):
                return
            if self.proc is not None:
                kill_tree(self.proc.pid)
        self.root.destroy()


# ============================================================
# 進入點 / Entry point
# ============================================================
def main() -> None:
    """建立視窗並進入主迴圈 / Create the window and enter the main loop."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)   # 高 DPI 螢幕上文字才不會模糊 / keeps text sharp on high-DPI screens
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    if not single_instance():
        root.withdraw()
        messagebox.showinfo(APP_TITLE, "控制面板已經開著了。\nThe control panel is already open.")
        return
    project = find_project()
    if project is None:
        root.withdraw()
        project = ask_project()
        if project is None:
            return
        root.deiconify()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    App(root, project)
    root.mainloop()


if __name__ == "__main__":
    main()
