"""畫面零件：全部畫在同一張 Canvas 上（漸層背景、半透明卡片、膠囊按鈕、狀態燈）

UI parts, all drawn on one Canvas: the gradient background, frosted cards, pill buttons and the status light.
因為都是自己畫的，背景才能透出來，和網頁看板一樣 / Everything is drawn by hand so the background shows through, like the web dashboard.
"""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import font as tkfont
from typing import Callable

from . import theme


def draw_background(cv: tk.Canvas, w: int, h: int, bands: int = 96) -> None:
    """畫由上到下的漸層背景（分成很多條細帶）/ Paint the vertical gradient as many thin bands."""
    cv.delete("bg")
    for i in range(bands):
        y0, y1 = h * i // bands, h * (i + 1) // bands + 1
        cv.create_rectangle(0, y0, w, y1, fill=theme.bg_at((i + 0.5) / bands), width=0, tags="bg")
    cv.tag_lower("bg")


def _round_points(x0: float, y0: float, x1: float, y1: float, r: float) -> list[float]:
    """圓角矩形的頂點（搭配 smooth=True 使用）/ The vertices of a rounded rectangle (use with smooth=True)."""
    return [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]


def draw_card(cv: tk.Canvas, x0: float, y0: float, x1: float, y1: float, r: float, fill: str, outline: str = theme.WHITE, tag: str = "") -> None:
    """圓角卡片（半透明玻璃的感覺）/ A rounded card with the frosted-glass look."""
    cv.create_polygon(_round_points(x0, y0, x1, y1, r), smooth=True, fill=fill, outline=outline, width=1, tags=tag)


def _pill_rows(cv: tk.Canvas, x0: float, y0: float, x1: float, y1: float, top: str, bottom: str, tag: str) -> None:
    """膠囊形狀、由上到下漸層：一列一列畫，兩端依圓的算式縮進 / A pill shape with a vertical gradient: drawn row by row, the ends inset by the circle formula."""
    h = y1 - y0
    r = h / 2
    rows = max(int(h), 1)
    for i in range(rows):
        y = y0 + i + 0.5
        dy = abs(y - (y0 + r))
        inset = r - math.sqrt(max(r * r - dy * dy, 0))
        cv.create_line(x0 + inset, y, x1 - inset, y, fill=theme.lerp(top, bottom, i / max(rows - 1, 1)), width=1.4, tags=tag)


class Pill:
    """一顆膠囊按鈕，kind：primary（主要）／ghost（次要）／danger（危險）

    A pill-shaped button. ``kind``: primary / ghost / danger. The same look as the dashboard's .btn-primary and .btn-ghost.
    """

    def __init__(self, cv: tk.Canvas, text: str, command: Callable[[], None], font, kind: str = "ghost") -> None:
        self.cv, self.text, self.command, self.font, self.kind = cv, text, command, font, kind
        self.enabled, self._hover, self._down = True, False, False
        self.box: tuple[float, float, float, float] = (0, 0, 0, 0)
        self.base = theme.CARD            # 按鈕後面的底色，用來算半透明 / the colour behind the button, for the translucency
        self.tag = f"pill{id(self)}"
        self._measure = tkfont.Font(cv, font=font)

    def width(self, pad: int = 22) -> int:
        """依文字算出需要的寬度 / The width needed for the text."""
        return self._measure.measure(self.text) + pad * 2

    def place(self, x: float, y: float, w: float, h: float, base: str) -> None:
        """放到 (x, y)，大小 w × h，base 是它後面的底色 / Put it at (x, y), size w x h; ``base`` is the colour behind it."""
        self.box, self.base = (x, y, x + w, y + h), base
        self.draw()

    def contains(self, x: float, y: float) -> bool:
        """座標是否落在按鈕範圍內 / Whether the point is inside the button."""
        x0, y0, x1, y1 = self.box
        return x0 <= x <= x1 and y0 <= y <= y1

    def set_enabled(self, on: bool) -> None:
        """啟用或停用（停用時變淡、點了沒反應）/ Enable or disable (dimmed and inert when disabled)."""
        if on != self.enabled:
            self.enabled = on
            self.draw()

    def set_text(self, text: str) -> None:
        """換文字 / Change the label."""
        self.text = text
        self.draw()

    def _colors(self) -> tuple[str, str, str, str | None]:
        """(上色, 下色, 文字色, 外框色) / (top, bottom, text, outline)."""
        base = self.base
        if self.kind == "primary":
            top, bottom, text, line = theme.ACCENT_LIGHT, theme.ACCENT, theme.WHITE, None
            if self._hover:
                top, bottom = theme.lerp(top, theme.WHITE, 0.18), theme.lerp(bottom, theme.WHITE, 0.14)
        elif self.kind == "danger":
            top, bottom, text, line = theme.glass(base, 0.66), theme.glass(base, 0.5), theme.ROSE_INK, theme.ROSE_DEEP
            if self._hover:
                top, bottom = theme.lerp(top, theme.ROSE, 0.55), theme.lerp(bottom, theme.ROSE, 0.45)
        else:
            top, bottom, text, line = theme.glass(base, 0.66), theme.glass(base, 0.5), theme.INK_2, theme.WHITE
            if self._hover:
                top, bottom, text = theme.glass(base, 0.9), theme.glass(base, 0.8), theme.INK
        if self._down:
            top, bottom = theme.lerp(top, theme.INK, 0.06), theme.lerp(bottom, theme.INK, 0.06)
        if not self.enabled:
            top, bottom = theme.lerp(top, base, 0.55), theme.lerp(bottom, base, 0.55)
            text = theme.lerp(text, base, 0.55)
            line = theme.lerp(line, base, 0.55) if line else None
        return top, bottom, text, line

    def draw(self) -> None:
        """（重新）畫出按鈕 / (Re)draw the button."""
        self.cv.delete(self.tag)
        x0, y0, x1, y1 = self.box
        if x1 <= x0:
            return
        top, bottom, text, line = self._colors()
        _pill_rows(self.cv, x0, y0, x1, y1, top, bottom, self.tag)
        if line:
            self.cv.create_polygon(_round_points(x0, y0, x1, y1, (y1 - y0) / 2), smooth=True, fill="", outline=line, tags=self.tag)
        self.cv.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=self.text, fill=text, font=self.font, tags=self.tag)

    def set_hover(self, on: bool) -> None:
        """滑鼠移上去／移開，只有狀態真的變了才重畫 / The pointer entered or left; redraw only when the state really changed."""
        on = on and self.enabled
        if on != self._hover:
            self._hover = on
            self.draw()

    def set_down(self, on: bool) -> None:
        """按下去／放開 / Pressed or released."""
        on = on and self.enabled
        if on != self._down:
            self._down = on
            self.draw()


class PillHub:
    """管這張 Canvas 上所有膠囊按鈕的滑鼠事件：用座標自己判斷落在哪顆，不替圖形綁事件

    Handles the mouse for every pill on a Canvas by hit-testing coordinates itself. Events are NOT bound to the drawn items:
    a button redraws by deleting and recreating its items, and with item bindings that made Tk send fresh Enter / Leave events
    under a resting pointer, which redrew again... an endless loop that froze the whole window (shown as "not responding").
    """

    def __init__(self, cv: tk.Canvas) -> None:
        self.cv, self.pills = cv, []
        self.hover: Pill | None = None
        self.pressed: Pill | None = None
        cv.bind("<Motion>", self._motion, add="+")
        cv.bind("<Leave>", self._leave, add="+")
        cv.bind("<ButtonPress-1>", self._press, add="+")
        cv.bind("<ButtonRelease-1>", self._release, add="+")

    def add(self, *pills: Pill) -> None:
        """登記按鈕 / Register buttons."""
        self.pills.extend(pills)

    def _at(self, x: float, y: float) -> Pill | None:
        return next((p for p in self.pills if p.contains(x, y)), None)

    def _motion(self, e) -> None:
        p = self._at(e.x, e.y)
        if p is self.hover:
            return
        if self.hover:
            self.hover.set_hover(False)
        self.hover = p
        if p:
            p.set_hover(True)
        self.cv.configure(cursor="hand2" if p and p.enabled else "")

    def _leave(self, _e=None) -> None:
        if self.hover:
            self.hover.set_hover(False)
        self.hover = None
        self.cv.configure(cursor="")

    def _press(self, e) -> None:
        self.pressed = self._at(e.x, e.y)
        if self.pressed:
            self.pressed.set_down(True)

    def _release(self, e) -> None:
        p, self.pressed = self.pressed, None
        if p is None:
            return
        p.set_down(False)
        if p.enabled and p.contains(e.x, e.y):
            p.command()


def draw_status_dot(cv: tk.Canvas, cx: float, cy: float, color: str, behind: str, tag: str) -> None:
    """狀態燈：圓點外面一圈淡淡的光（同看板的 .status::before）/ The status light: a dot with a soft ring (as the dashboard's .status::before)."""
    cv.create_oval(cx - 9, cy - 9, cx + 9, cy + 9, fill=theme.lerp(color, behind, 0.72), width=0, tags=tag)
    cv.create_oval(cx - 5, cy - 5, cx + 5, cy + 5, fill=color, width=0, tags=tag)


def draw_logo(cv: tk.Canvas, cx: float, cy: float, r: float, tag: str) -> None:
    """唱片形狀的 logo（同看板左上角）/ The record-disc logo (as the dashboard's top left)."""
    cv.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#7F8EC1", outline=theme.WHITE, width=2, tags=tag)
    cv.create_oval(cx - r * 0.62, cy - r * 0.62, cx + r * 0.62, cy + r * 0.62, fill="", outline=theme.lerp("#7F8EC1", theme.WHITE, 0.45), width=1, tags=tag)
    cv.create_oval(cx - r * 0.3, cy - r * 0.3, cx + r * 0.3, cy + r * 0.3, fill=theme.CREAM, outline="", tags=tag)
    cv.create_oval(cx - r * 0.1, cy - r * 0.1, cx + r * 0.1, cy + r * 0.1, fill=theme.STEEL, outline="", tags=tag)
