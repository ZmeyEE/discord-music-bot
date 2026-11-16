"""按鈕的動作：啟動、停止、重新啟動、監看狀態（耗時的事在背景執行緒）

What the buttons do: start, stop, restart and watching the state (slow work in helper threads)
"""
from __future__ import annotations

import os
import threading
from tkinter import messagebox

from .paths import APP_TITLE
from .procs import find_external_bots


class ActionsMixin:
    def running(self) -> bool:
        """本程式啟動的機器人是否還在跑 / Is the bot started by this panel still running?"""
        return self.runner.running()

    def set_state(self, kind: str, detail: str = "") -> None:
        """更新狀態燈與按鈕可用性，kind：running / stopped / starting / stopping / crashed

        Update the status light and which buttons are enabled.
        ``kind`` is one of: running / stopped / starting / stopping / crashed.
        """
        self.kind, self.detail = kind, detail
        idle = not self.busy
        on = kind in ("running", "starting")
        self.b_start.set_enabled(idle and not on)
        self.b_stop.set_enabled(idle and kind != "stopped")
        self.b_restart.set_enabled(idle and kind in ("running", "crashed"))
        self.redraw()

    def poll(self) -> None:
        """每秒檢查機器人是否自己結束了（例如連線錯誤、被外部關掉）

        Once a second, check whether the bot ended by itself (a connection error, closed from outside...).
        """
        if not self.busy:
            code = self.runner.finished()
            if code is not None:
                if code == 0:
                    self.say("機器人已結束。", "sys")
                    self.set_state("stopped")
                else:
                    self.say(f"機器人意外結束（代碼 {code}），請看上面的紀錄找原因。", "err")
                    self.set_state("crashed", f"代碼 {code}")
        self.root.after(1000, self.poll)

    def work(self, fn) -> None:
        """在背景執行緒做耗時的事，並鎖住按鈕避免連點 / Run slow work in a background thread and lock the buttons meanwhile."""
        self.busy = True
        threading.Thread(target=fn, daemon=True).start()

    def check_external_on_open(self) -> None:
        """開啟時掃描一次：有沒有別處啟動的機器人 / Scan once at start-up: is a bot already running from somewhere else?"""
        def go() -> None:
            pids = find_external_bots(self.project)
            self.post(lambda: self.after_scan_on_open(pids))
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
        if not self.runner.python().exists():
            messagebox.showerror(APP_TITLE, f"找不到 Python 環境：\n{self.runner.python()}\n\n請見 README 建立 .venv。\nPython environment not found - see the README to create the .venv.")
            return
        self.set_state("starting")
        self.work(self._start_worker)

    def _start_worker(self) -> None:
        """（背景執行緒）啟動機器人 / (Background thread) start the bot."""
        try:
            self.runner.start()
            self.post(lambda: self._done("running", "已啟動"))
        except OSError as e:
            self.lines.put(f"[控制面板] 啟動失敗：{e}")
            self.post(lambda: self._done("crashed", "啟動失敗"))

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
        """（背景執行緒）停止機器人 / (Background thread) stop the bot."""
        self.runner.stop()
        self.post(lambda: (self._done("stopped"), then() if then else None))

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
        """關閉視窗：自己開的機器人會問一聲並一併停止；不是這個視窗開的（外部啟動）也要問，免得關了視窗它還躲在背景跑

        Closing the window: a bot we started is confirmed and stopped with it. A bot started elsewhere (start.bat...) is asked about too,
        so it doesn't keep running hidden in the background after the window is gone.
        """
        stop = None   # 要在背景執行緒做的停止動作 / the stop to run in a helper thread
        if self.running() or self.busy:
            if not messagebox.askokcancel(APP_TITLE, "機器人還在執行。\n關閉視窗會一併停止機器人，確定要關閉嗎？\nThe bot is still running; closing the window stops it too. Continue?"):
                return
            stop = self.runner.kill_own
        elif self.kind == "running":   # 外部啟動的機器人 / a bot started elsewhere
            ans = messagebox.askyesnocancel(
                APP_TITLE,
                "有機器人在背景執行（不是這個視窗開的）。\n要一併關掉它嗎？\n\n是：關掉機器人再關閉視窗\n否：機器人繼續跑，只關閉視窗\n取消：不關閉\n\n"
                "A bot started elsewhere is still running.\nYes: stop it and close   No: leave it running   Cancel: stay open",
            )
            if ans is None:
                return
            if ans:
                stop = self.runner.stop
        if stop is None:
            self.root.destroy()
            return
        # 停止要好幾秒（掃描程序、taskkill），在主執行緒做視窗會變"沒有回應"，所以丟到背景，做完再關視窗
        # Stopping takes seconds (process scan, taskkill); on the main thread the window would show "not responding", so do it in the background and close afterwards.
        self.busy = True
        self.set_state("stopping")
        threading.Thread(target=lambda: (stop(), self.post(self.root.destroy)), daemon=True).start()
