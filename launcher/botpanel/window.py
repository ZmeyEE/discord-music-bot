"""控制面板視窗：狀態燈、啟動／停止／重新啟動、即時紀錄（配色與按鈕和網頁看板一致）

The control-panel window: a status light, Start / Stop / Restart and a live log, styled like the web dashboard.
畫面的事都在主執行緒；耗時的事（啟動、停止、掃描）在背景執行緒做，做完用 ``post`` 交回主執行緒
動作在 actions.py，紀錄區在 logview.py，這個檔案只管畫面
UI work stays on the main thread; slow work (starting, stopping, scanning) runs in helper threads and hands back with ``post``.
The actions are in actions.py and the log area in logview.py; this file only paints the window.
"""
from __future__ import annotations

import queue
import sys
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import ttk

from . import __version__, theme
from .actions import ActionsMixin
from .logview import LogMixin
from .paths import APP_TITLE, dashboard_url
from .procs import BotRunner
from .widgets import Pill, PillHub, draw_background, draw_card, draw_logo, draw_status_dot

MARGIN = 22

# 狀態 -> (文字, 燈的顏色) / state -> (text, light colour)
LOOKS = {
    "running": ("執行中", theme.OK), "stopped": ("已停止", theme.INK_3), "starting": ("啟動中…", theme.AMBER),
    "stopping": ("停止中…", theme.AMBER), "crashed": ("異常結束", theme.ROSE_DEEP),
}


class App(ActionsMixin, LogMixin):
    """控制面板視窗 / The control-panel window."""

    def __init__(self, root: tk.Tk, project: Path) -> None:
        self.root = root
        self.project = project
        self.url = dashboard_url(project)
        self.lines: queue.Queue[str] = queue.Queue()      # 背景執行緒把機器人輸出丟進來，主執行緒再顯示 / helper threads drop the bot's output here
        self.calls: queue.Queue = queue.Queue()           # 背景執行緒要主執行緒做的事（tkinter 只能在主執行緒碰）/ things helper threads ask the main thread to do (tkinter must only be touched there)
        self.runner = BotRunner(project, self.lines)
        self.busy = False                                  # 啟動／停止進行中，避免連點 / a start/stop is in progress; prevents double clicks
        self.kind, self.detail = "stopped", ""
        self.fonts = theme.Fonts(root)

        root.title(APP_TITLE)
        if getattr(sys, "frozen", False):   # 打包成 exe 時，視窗和工作列用 exe 自己的圖示 / packaged exe: the window and taskbar use the exe's own icon
            try:
                root.iconbitmap(sys.executable)
            except tk.TclError:
                pass
        root.geometry("780x560")
        root.minsize(740, 440)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._style_scrollbar()

        self.cv = tk.Canvas(root, highlightthickness=0, bd=0, bg=theme.CREAM)
        self.cv.pack(fill="both", expand=True)
        self._build_log()
        self._build_buttons()
        self._redraw_job = None
        self.cv.bind("<Configure>", self._on_resize)

        self.say(f"專案 / Project：{project}", "sys")
        self.set_state("stopped")
        self.pump()
        self.poll()
        root.after(400, self.check_external_on_open)

    def _style_scrollbar(self) -> None:
        """捲軸換成和卡片搭的顏色 / Colour the scrollbar to match the card."""
        st = ttk.Style(self.root)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure("Vertical.TScrollbar", troughcolor=theme.CARD, background=theme.ROSE, bordercolor=theme.CARD,
                     lightcolor=theme.ROSE, darkcolor=theme.ROSE, arrowcolor=theme.INK_3, relief="flat")
        st.map("Vertical.TScrollbar", background=[("active", theme.LAVENDER)])

    def _build_log(self) -> None:
        """紀錄區：卡片上的文字框 / The log area: a text box on a card."""
        self.log = tk.Text(
            self.cv, wrap="none", state="disabled", font=self.fonts.mono, bg=theme.CARD, fg=theme.INK, relief="flat", bd=0,
            insertbackground=theme.INK, selectbackground=theme.LAVENDER, padx=4, pady=2, highlightthickness=0,
        )
        self.scroll = ttk.Scrollbar(self.cv, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=self.scroll.set)
        self.log.tag_configure("err", foreground=theme.LOG_ERR)
        self.log.tag_configure("ok", foreground=theme.LOG_OK)
        self.log.tag_configure("sys", foreground=theme.LOG_SYS)
        self._log_win = self.cv.create_window(0, 0, anchor="nw", window=self.log)
        self._scroll_win = self.cv.create_window(0, 0, anchor="ne", window=self.scroll)

    def _build_buttons(self) -> None:
        """六顆按鈕：左邊三顆控制（放在一個膠囊裡），右邊三顆工具 / Six buttons: three controls in a pill on the left, three tools on the right."""
        f = self.fonts.button
        self.b_start = Pill(self.cv, "▶  啟動", self.start, f, "primary")
        self.b_stop = Pill(self.cv, "■  停止", self.stop, f, "danger")
        self.b_restart = Pill(self.cv, "↻  重新啟動", self.restart, f, "ghost")
        self.b_open = Pill(self.cv, "開啟看板", lambda: webbrowser.open(self.url), f, "primary")
        self.b_folder = Pill(self.cv, "專案資料夾", self.open_folder, f, "ghost")
        self.b_clear = Pill(self.cv, "清除紀錄", self.clear_log, f, "ghost")
        self.controls = (self.b_start, self.b_stop, self.b_restart)
        self.tools = (self.b_clear, self.b_folder, self.b_open)
        self.pills = PillHub(self.cv)          # 滑鼠事件由它用座標判斷，不綁在圖形上（見 widgets.PillHub）/ mouse events by hit-testing, not bound to items (see widgets.PillHub)
        self.pills.add(*self.controls, *self.tools)

    def _on_resize(self, _e=None) -> None:
        """視窗大小變了：稍等一下再重畫，拖曳時不要每格都畫 / Window resized: redraw after a short pause, not on every pixel of a drag."""
        if self._redraw_job:
            self.root.after_cancel(self._redraw_job)
        self._redraw_job = self.root.after(30, self.redraw)

    def redraw(self) -> None:
        """整張重畫（背景、標題、狀態、按鈕、卡片）/ Repaint everything: background, title, status, buttons, card."""
        self._redraw_job = None
        cv, w, h = self.cv, self.cv.winfo_width(), self.cv.winfo_height()
        if w < 50 or h < 50:
            return
        cv.delete("ui")
        draw_background(cv, w, h)
        top_color = theme.bg_at(0.05)

        # 標題列：logo、名稱、狀態 / header: logo, name, status
        draw_logo(cv, MARGIN + 22, 40, 18, "ui")
        tid = cv.create_text(MARGIN + 54, 30, text=APP_TITLE, anchor="w", font=self.fonts.title, fill=theme.INK, tags="ui")
        cv.create_text(cv.bbox(tid)[2] + 8, 34, text=f"v{__version__}", anchor="w", font=self.fonts.small, fill=theme.INK_3, tags="ui")
        text, color = LOOKS[self.kind]
        draw_status_dot(cv, MARGIN + 63, 58, color, top_color, "ui")
        sid = cv.create_text(MARGIN + 80, 58, text=text, anchor="w", font=self.fonts.button, fill=theme.INK_2, tags="ui")
        if self.detail:
            x1 = cv.bbox(sid)[2]
            cv.create_text(x1 + 10, 58, text=self.detail, anchor="w", font=self.fonts.small, fill=theme.INK_3, tags="ui")

        # 按鈕列 / button row
        y0, bh = 84, 38
        pad, gap = 5, 4
        cw = sum(b.width() for b in self.controls) + gap * 2 + pad * 2
        seg_base = theme.glass(theme.bg_at(0.16), 0.5)
        draw_card(cv, MARGIN, y0, MARGIN + cw, y0 + bh + pad * 2, (bh + pad * 2) / 2, seg_base, theme.WHITE, "ui")
        x = MARGIN + pad
        for b in self.controls:
            b.place(x, y0 + pad, b.width(), bh, seg_base)
            x += b.width() + gap
        x = w - MARGIN
        for b in self.tools:
            x -= b.width()
            b.place(x, y0 + pad, b.width(), bh, theme.bg_at(0.16))
            x -= 8

        # 紀錄卡片 / the log card
        cy0, cy1 = y0 + bh + pad * 2 + 18, h - MARGIN
        draw_card(cv, MARGIN, cy0, w - MARGIN, cy1, 20, theme.CARD, theme.WHITE, "ui")
        cv.create_text(MARGIN + 22, cy0 + 20, text="即時紀錄  Live log", anchor="w", font=self.fonts.small, fill=theme.INK_3, tags="ui")
        self.cv.coords(self._log_win, MARGIN + 18, cy0 + 38)
        self.cv.itemconfigure(self._log_win, width=max(w - 2 * MARGIN - 52, 80), height=max(cy1 - cy0 - 56, 40))
        self.cv.coords(self._scroll_win, w - MARGIN - 12, cy0 + 38)
        self.cv.itemconfigure(self._scroll_win, height=max(cy1 - cy0 - 56, 40))
        cv.tag_raise(self._log_win)
        cv.tag_raise(self._scroll_win)
        for b in (*self.controls, *self.tools):
            cv.tag_raise(b.tag)
