"""程序控制：單一實例、找出外部開的機器人、結束程序、啟動和停止機器人

Process control: the single-instance guard, finding bots started elsewhere, killing processes, starting and stopping the bot.
這個檔案完全不碰畫面，所以可以單獨測試 / Nothing here touches the UI, so it can be tested on its own.
"""
from __future__ import annotations

import ctypes
import os
import queue
import subprocess
import threading
from pathlib import Path

MUTEX_NAME = "Local\\DiscordMusicBotLauncher"   # 單一實例用的 Windows 互斥鎖名稱 / Windows mutex name for the single-instance guard
NO_WINDOW = 0x08000000                           # CREATE_NO_WINDOW：子程序不要跳出黑色視窗 / CREATE_NO_WINDOW: no console window for child processes


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
    return parse_external(out, project)


def parse_external(out: str, project: Path) -> list[int]:
    """從 PowerShell 的輸出挑出"這個專案的 .venv 的 python"，不會誤殺別的 bot.py

    Pick the processes that belong to THIS project's .venv from the PowerShell output, so some other bot.py is never killed.
    """
    key = str(project / ".venv").lower()
    pids: list[int] = []
    for line in out.splitlines():
        pid, _, exe = line.partition("|")
        if pid.strip().isdigit() and exe.strip().lower().startswith(key):
            pids.append(int(pid))
    return pids


def kill_tree(pid: int) -> None:
    """結束一個程序與它底下所有子程序（/T）/ Kill a process together with all of its children (/T)."""
    run_hidden(["taskkill", "/PID", str(pid), "/T", "/F"], timeout=20)


class BotRunner:
    """啟動、停止、監看機器人；輸出一行一行放進 ``out`` 佇列，由畫面去顯示

    Start, stop and watch the bot. Its output goes line by line into the ``out`` queue for the UI to show.
    """

    def __init__(self, project: Path, out: "queue.Queue[str]") -> None:
        self.project = project
        self.out = out
        self.proc: subprocess.Popen | None = None

    def python(self) -> Path:
        """專案 .venv 裡的 python / The python of the project's .venv."""
        return self.project / ".venv" / "Scripts" / "python.exe"

    def running(self) -> bool:
        """本程式啟動的機器人是否還在跑 / Is the bot started by this panel still running?"""
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> None:
        """關掉外部的舊機器人、啟動新的，並開始讀它的輸出（可能花幾秒，請在背景執行緒呼叫）

        Close any external bot, start a new one and begin reading its output (may take seconds: call it from a thread).
        Raises OSError when the process cannot be started.
        """
        ext = find_external_bots(self.project)
        if ext:
            self.out.put(f"[控制面板] 偵測到已有機器人在跑（{ext}），先關掉它避免重複登入…")
            for p in ext:
                kill_tree(p)
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        self.proc = subprocess.Popen(
            [str(self.python()), "-X", "utf8", "-u", "bot.py"], cwd=str(self.project), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            creationflags=NO_WINDOW,
        )
        threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()
        self.out.put("[控制面板] 機器人啟動中…")

    def _reader(self, proc: subprocess.Popen) -> None:
        """（背景執行緒）一行一行讀機器人的輸出 / (Background thread) read the bot's output line by line."""
        assert proc.stdout is not None
        for raw in iter(proc.stdout.readline, b""):
            self.out.put(raw.decode("utf-8", "replace"))

    def stop(self) -> None:
        """結束自己啟動的機器人，也一併結束外部啟動的 / Stop our own bot and any externally started one."""
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
        self.out.put("[控制面板] 機器人已停止。")

    def finished(self) -> int | None:
        """機器人自己結束了就回傳結束代碼（並清掉），還在跑回傳 None / The exit code once the bot ended by itself (and clear it), None while it runs."""
        if self.proc is not None and self.proc.poll() is not None:
            code = self.proc.returncode
            self.proc = None
            return code
        return None

    def kill_own(self) -> None:
        """關視窗時：只結束自己啟動的那個 / On window close: kill only the one we started."""
        if self.proc is not None:
            kill_tree(self.proc.pid)
