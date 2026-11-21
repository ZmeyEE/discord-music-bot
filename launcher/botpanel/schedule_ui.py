"""每日定時重啟的畫面與排程：右上角的小按鈕、設定對話框、每隔幾秒看一次時間

The daily restart's UI and timer: the small pill, the settings dialog, and the clock check every few seconds.
只有「機器人正在執行」才會重啟；已停止、異常結束的不會被叫起來 / Only a RUNNING bot is restarted; a stopped or crashed one is left alone.
"""
from __future__ import annotations

import tkinter as tk
from datetime import datetime
from tkinter import messagebox

from . import schedule, theme
from .paths import APP_TITLE


class ScheduleMixin:
    def init_schedule(self) -> None:
        """讀設定、排好下一次時間、開始看時間 / Load the settings, work out the next run and start watching the clock."""
        self.sched_on, self.sched_time = schedule.load()
        self.sched_due = schedule.next_run(datetime.now(), self.sched_time) if self.sched_on else None
        self.dialog = None
        self.root.after(schedule.TICK_MS, self.schedule_tick)

    def sched_label(self) -> str:
        """按鈕上的字 / The pill's text."""
        return f"⏰ 每日重啟 {self.sched_time}" if self.sched_on else "⏰ 每日重啟：關"

    def apply_schedule(self, on: bool, hhmm: str) -> None:
        """套用並存檔；存不進去只提醒一聲，這次開著期間照樣有效 / Apply and save; if saving fails just say so, it still works while the panel is open."""
        self.sched_on, self.sched_time = on, hhmm
        self.sched_due = schedule.next_run(datetime.now(), hhmm) if on else None
        try:
            schedule.save(on, hhmm)
        except OSError as e:
            self.say(f"[控制面板] 每日重啟設定存不進檔案：{e}", "err")
        self.say(f"每日重啟：{'每天 ' + hhmm + ' 自動重新啟動機器人' if on else '已關閉'}", "sys")
        self.b_sched.set_text(self.sched_label())
        self.redraw()

    def schedule_tick(self) -> None:
        """每隔幾秒：到時間就重啟（任何錯誤都不能讓計時停掉）/ Every few seconds: restart when due (nothing may stop the timer for good)."""
        try:
            self.check_schedule(datetime.now())
        except Exception as e:  # noqa: BLE001
            self.say(f"[控制面板] 每日重啟檢查出錯：{e}", "err")
        self.root.after(schedule.TICK_MS, self.schedule_tick)

    def check_schedule(self, now: datetime) -> None:
        """看一次：到了而且機器人在跑就重啟；正在啟動／停止中就下一輪再看（寬限時間內都算數）

        One check: when due and the bot is running, restart it; while it is starting or stopping, look again next round (counts within the grace time).
        """
        if not self.sched_on or self.sched_due is None:
            return
        v = schedule.verdict(now, self.sched_due)
        if v == "wait" or (v == "fire" and self.busy):
            return
        due, self.sched_due = self.sched_due, schedule.next_run(now, self.sched_time)
        if v == "skip":
            self.say(f"每日重啟：錯過了 {due:%H:%M}（電腦睡著或面板卡住），今天略過", "sys")
        elif self.kind == "running":
            self.say(f"每日重啟：到了 {due:%H:%M}，重新啟動機器人", "sys")
            self.restart()
        else:
            self.say(f"每日重啟：到了 {due:%H:%M}，但機器人沒有在執行，不處理", "sys")

    def open_schedule(self) -> None:
        """設定對話框：開關 ＋ 時 ＋ 分 / The settings dialog: a switch plus hour and minute."""
        if self.dialog is not None and self.dialog.winfo_exists():
            self.dialog.lift()
            return
        d = self.dialog = tk.Toplevel(self.root)
        d.title("每日重啟")
        d.configure(bg=theme.CREAM, padx=22, pady=18)
        d.resizable(False, False)
        d.transient(self.root)
        f, small = self.fonts.body, self.fonts.small
        h0, m0 = (int(x) for x in self.sched_time.split(":"))
        on, hh, mm = tk.BooleanVar(d, self.sched_on), tk.StringVar(d, f"{h0:02d}"), tk.StringVar(d, f"{m0:02d}")

        tk.Checkbutton(d, text="每天定時重新啟動機器人", variable=on, font=f, bg=theme.CREAM, fg=theme.INK, activebackground=theme.CREAM,
                       selectcolor=theme.CARD, anchor="w").grid(row=0, column=0, columnspan=4, sticky="w")
        tk.Label(d, text="時間（24 小時制）", font=f, bg=theme.CREAM, fg=theme.INK_2).grid(row=1, column=0, sticky="w", pady=(12, 0))
        spin = dict(width=3, font=f, justify="center", format="%02.0f", wrap=True, bg=theme.CARD, fg=theme.INK, relief="flat")
        box = tk.Frame(d, bg=theme.CREAM)    # 時、冒號、分擠在一起，不被欄寬拉開 / hour, colon and minute kept together
        box.grid(row=1, column=1, columnspan=3, sticky="w", padx=(10, 0), pady=(12, 0))
        tk.Spinbox(box, from_=0, to=23, textvariable=hh, **spin).pack(side="left")
        tk.Label(box, text=" : ", font=f, bg=theme.CREAM, fg=theme.INK_2).pack(side="left")
        tk.Spinbox(box, from_=0, to=59, textvariable=mm, **spin).pack(side="left")
        tk.Label(d, text="到時間若機器人正在執行，會自動停止再啟動（正在播的歌會中斷）。\n已停止的不會被啟動；電腦睡著錯過了就略過那一天。\n控制面板要保持開著才會生效。",
                 font=small, bg=theme.CREAM, fg=theme.INK_3, justify="left").grid(row=2, column=0, columnspan=4, sticky="w", pady=(12, 0))

        def ok() -> None:
            t = schedule.parse_time(f"{hh.get()}:{mm.get()}")
            if t is None:
                messagebox.showerror(APP_TITLE, "時間不對，請輸入 00:00 ～ 23:59。\nInvalid time, use 00:00-23:59.", parent=d)
                return
            self.apply_schedule(on.get(), t)
            d.destroy()

        row = tk.Frame(d, bg=theme.CREAM)
        row.grid(row=3, column=0, columnspan=4, sticky="e", pady=(16, 0))
        tk.Button(row, text="取消", command=d.destroy, font=f, bg=theme.CARD, fg=theme.INK_2, relief="flat", padx=14, pady=3).pack(side="left", padx=(0, 8))
        self.dialog_ok = tk.Button(row, text="確定", command=ok, font=f, bg=theme.ACCENT, fg=theme.WHITE, relief="flat", padx=14, pady=3)
        self.dialog_ok.pack(side="left")
        d.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - d.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - d.winfo_height()) // 3
        d.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        d.grab_set()
