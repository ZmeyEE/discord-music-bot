"""Hub 用到的資料結構

Data structures used by the Hub
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Awaitable, Callable, NamedTuple

import discord

from ..player import PlayerBot

if TYPE_CHECKING:
    pass


Emit = Callable[[dict], Awaitable[None]]   # 把訊息只傳給"發出請求的那個瀏覽器"/ send a message to only the browser that made the request


@dataclass(frozen=True)
class UserCtx:
    """後台連線者的身分

    Who a dashboard connection is (identity + privileges).
    """
    user_id: int | None        # Discord 使用者 ID；本地直接開的後台沒有 / Discord user id; None for the local dashboard
    name: str
    is_host: bool = False      # 從執行機器人的這台電腦直接開（localhost）/ opened directly on the machine running the bot (localhost)
    is_owner: bool = False     # 機器人（應用程式）的擁有者 / the owner of the bot application
    pending: bool = False      # 驗證模式：還沒用 /help 的專屬連結確認身分（什麼都不能做，只會看到"請用連結進來"）/ verify mode: identity not yet confirmed via the /help link (nothing allowed; only sees "use the link")
    via: str = ""              # 身分從哪來：device（記住的裝置）／link（/help 的連結）／local／guest／pending / where the identity came from: device (remembered) / link (/help) / local / guest / pending


class Player(NamedTuple):
    """一個"機器人帳號 × 伺服器"的組合，附帶幾個方便的屬性

    A (bot account, server) pair with a few convenience properties.
    """
    worker: PlayerBot
    guild: discord.Guild

    @property
    def pid(self) -> str:
        return self.worker.pid

    @property
    def vc(self):
        """該伺服器裡這個機器人的語音連線（沒在語音頻道就是 None） / This bot's voice connection in that server (None when not in voice)."""
        return self.guild.voice_client

    @property
    def state(self):
        return self.worker.state(self.guild.id)


_EMPTY_PLAYER = {"connected": False, "channel": None, "paused": False, "loop": "off", "current": None, "queue": [], "queue_total": 0}   # 沒有播放器時給前端的空狀態 / the empty state sent to the front-end when no player is selected
