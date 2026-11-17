"""紀錄區：加一行、清除、把背景執行緒的輸出搬到畫面

The log area: append a line, clear it, and move helper-thread output onto the screen
"""
from __future__ import annotations

import queue

MAX_LOG_LINES = 800   # 視窗裡最多保留幾行紀錄 / how many log lines the window keeps


class LogMixin:
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

    def post(self, fn) -> None:
        """（任何執行緒）請主執行緒執行 fn / (Any thread) ask the main thread to run fn."""
        self.calls.put(fn)

    def pump(self) -> None:
        """每 0.1 秒：執行背景執行緒交代的事，再把佇列裡的輸出搬到畫面上（一次最多 200 行，避免卡住介面）

        Every 0.1 s: run what helper threads asked for, then move queued output onto the screen (at most 200 lines per round so the UI stays responsive).
        """
        while True:
            try:
                fn = self.calls.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception:  # noqa: BLE001 - 一個回呼出錯不能讓整個記錄區停止更新 / one failing callback must not stop the log view for good
                pass
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
