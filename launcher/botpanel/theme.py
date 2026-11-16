"""配色與字體：和網頁看板同一套"黃昏雲海"（顏色對照 web/style.css 最上面的 :root）

Colours and fonts: the same "dusk sea of clouds" palette as the web dashboard (see the :root block at the top of web/style.css).
"""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont

# --- 色票 / palette（同 web/style.css）---
CREAM, ROSE, LAVENDER, STEEL = "#F7E0D3", "#E3C2C6", "#AFAFC8", "#5F7EAE"
INK, INK_2, INK_3 = "#33405E", "#5D6A8C", "#8791AE"          # 主要／次要／輔助文字 / main, secondary, tertiary text
ACCENT, ACCENT_LIGHT = "#54739F", "#6C8AB8"                  # 主要按鈕 / primary buttons
ROSE_DEEP, ROSE_INK = "#C98C99", "#9C5B6B"                   # 危險與錯誤 / danger and errors
OK, AMBER = "#6BB59A", "#DDAA6E"                             # 狀態燈：正常／處理中 / status light: ok / busy
CARD = "#FFF9F4"                                              # 卡片底色（紀錄區）/ card colour (the log area)
WHITE = "#FFFFFF"

# 背景：由上到下的漸層（同看板 body::before 的 linear-gradient）/ the vertical background gradient (as the dashboard's body::before)
BG_STOPS = ((0.0, "#AFA3CB"), (0.32, "#C9B3CE"), (0.66, "#E6C8BF"), (1.0, "#F7E0D3"))

# 紀錄區文字顏色 / log text colours
LOG_ERR, LOG_OK, LOG_SYS = "#B04A5E", "#3F7D66", ACCENT


def _rgb(c: str) -> tuple[int, int, int]:
    return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)


def lerp(c1: str, c2: str, t: float) -> str:
    """兩個顏色之間插值 / Interpolate between two colours (t = 0..1)."""
    a, b = _rgb(c1), _rgb(c2)
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def bg_at(t: float) -> str:
    """背景漸層在 t（0 = 最上、1 = 最下）的顏色 / The background gradient colour at t (0 = top, 1 = bottom)."""
    t = min(max(t, 0.0), 1.0)
    for (t0, c0), (t1, c1) in zip(BG_STOPS, BG_STOPS[1:]):
        if t <= t1:
            return lerp(c0, c1, (t - t0) / (t1 - t0))
    return BG_STOPS[-1][1]


def glass(base: str, alpha: float = 0.6) -> str:
    """把白色以 alpha 疊在 base 上，模擬看板的半透明玻璃卡片 / White laid over ``base`` at ``alpha``: the dashboard's frosted-glass card."""
    return lerp(base, WHITE, alpha)


class Fonts:
    """字體：有粉圓 Huninn 就用，沒有就用系統的微軟正黑體 / Fonts: Huninn when installed, otherwise Microsoft JhengHei UI."""

    def __init__(self, root: tk.Misc) -> None:
        names = set(tkfont.families(root))
        ui = next((f for f in ("Huninn", "Microsoft JhengHei UI", "Segoe UI") if f in names), "TkDefaultFont")
        mono = next((f for f in ("Cascadia Mono", "Consolas", "Courier New") if f in names), "TkFixedFont")
        self.title = (ui, 15, "bold")
        self.body = (ui, 10)
        self.button = (ui, 10, "bold")
        self.small = (ui, 9)
        self.mono = (mono, 10)
