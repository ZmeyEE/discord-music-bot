"""一個瀏覽器連線的資料，與暱稱清理

The record of one browser connection, and nickname cleaning
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from ..hub import UserCtx
from .queuewindow import QueueView

Emit = Callable[[dict], Awaitable[None]]   # "把一則訊息送給某個瀏覽器"的函式型別 / type of "send one message to one browser"


def clean_name(raw: object) -> str:
    """訪客暱稱：只留可顯示字元、最多 16 字

    Guest nickname: keep printable characters only, at most 16 characters.
    """
    return "".join(ch for ch in str(raw or "") if ch.isprintable()).strip()[:16]


@dataclass(eq=False)
class Session:
    """一個瀏覽器分頁

    One browser tab connected to the dashboard.
    """
    gid: int                                        # 它看的是哪個伺服器 / which guild (server) it is looking at
    ctx: UserCtx                                    # 它是誰、能做什麼 / who it is and what it may do
    emit: Emit                                      # 把訊息送回這個瀏覽器 / sends a message back to this browser
    pid: str | None = None                          # 使用者在介面上選的播放器；None = 自動跟著他所在的頻道 / the player picked in the UI; None = follow the channel the user is in
    bili_task: asyncio.Task | None = None           # 進行中的 Bilibili QR 登入流程 / the running Bilibili QR-login flow, if any
    view: QueueView = field(default_factory=QueueView)   # 它的待播清單視窗（見 queuewindow.py）/ its queue window (see queuewindow.py)
