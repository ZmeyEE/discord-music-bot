"""Hub：所有播放器的總指揮（主機器人與分身），決定誰能控制

功能都拆在同資料夾的檔案裡，這裡只負責組起來和 Discord 事件

Hub: the conductor of all players (main bot and clones), decides who may control.

The features live in the sibling files; this file only assembles them and handles Discord events
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import discord

from .. import config
from ..members import Registry
from ..paths import MEMBERS_FILE
from ..player import PlayerBot
from .actions import ActionsMixin
from .bili import BiliMixin
from .identity import IdentityMixin
from .routing import RoutingMixin
from .snapshot import SnapshotMixin
from .streams import StreamsMixin

if TYPE_CHECKING:
    from ..dashboard import Dashboard
log = logging.getLogger("musicbot")


class Hub(IdentityMixin, RoutingMixin, StreamsMixin, SnapshotMixin, ActionsMixin, BiliMixin):
    """所有播放器的總指揮

    The conductor of all players. One Hub exists per process.
    """
    def __init__(self) -> None:
        self.workers: list[PlayerBot] = []
        self.dashboard: "Dashboard | None" = None
        self._core = None
        self.base_url = ""
        self.owner_ids: set[int] = set()
        self.secret = config.dashboard_secret()
        self.mode = config.dashboard_mode()                 # open / verify / voice
        self.open_access = self.mode == "open"              # 任何人都能進（也決定 /api/guilds 要不要公開）/ anyone may enter (also decides whether /api/guilds is public)
        self.free_control = self.mode != "voice"            # 進得來的人可以控制所有頻道（語音模式才限制在自己的頻道）/ whoever gets in may control every channel (only voice mode restricts to your own channel)
        self.members = Registry(MEMBERS_FILE)               # 驗證過的成員與裝置（存在這台電腦）/ verified members and devices (stored on this machine)
        self._member_cache: dict[tuple[int, int], tuple[float, str | None]] = {}
        self._avatar_cache: dict[tuple[int, int], str] = {}
        self._ceiling: int | None = None                    # 卡頓偵測停掉頻道後，暫時壓住的同時播放數 / the temporary cap on simultaneous streams after the stutter detector removed one
        self._ceiling_until = 0.0                           # ……壓到什麼時候（monotonic）/ ...until when (monotonic)
        self.limit_notice: dict | None = None               # 最近一次停止頻道的公告（看板橫幅用）/ the latest "channel stopped" announcement (dashboard banner)

    @property
    def primary(self) -> PlayerBot:
        """主機器人（第一個帳號） / The main bot (the first account)."""
        return self.workers[0]

    @property
    def core(self):
        """看板核心（工作階段／權限／廣播），本地後台與遠端中繼站共用，延遲建立以避免循環匯入

        The dashboard core (sessions / permissions / broadcast), shared by the local dashboard and the
        remote relay. Created lazily to avoid a circular import.
        """
        if self._core is None:
            from ..dashboard import DashboardCore
            self._core = DashboardCore(self)
        return self._core

    def notify(self, guild_id: int) -> None:
        """某個伺服器的狀態變了：請看板重新廣播 / A server's state changed: ask the dashboard to broadcast again."""
        if self._core is not None:
            self._core.broadcast(guild_id)

    async def on_worker_ready(self, worker: PlayerBot) -> None:
        """某個機器人登入完成，主機器人要查出擁有者並檢查 Bilibili 登入

        A bot finished logging in. The main bot looks up the owners and re-checks the Bilibili login.
        """
        if worker.is_primary:
            try:
                info = await worker.application_info()
                self.owner_ids = {info.owner.id} | {m.id for m in (info.team.members if info.team else [])}
            except discord.HTTPException as exc:
                log.warning("無法取得機器人擁有者資訊：%s", exc)
            asyncio.create_task(self.refresh_bili())

    async def on_guild_join(self, worker: PlayerBot, guild: discord.Guild) -> None:
        """主機器人被邀請進新伺服器時，在系統頻道丟一則快速上手說明

        When the main bot is invited to a new server, post a quick-start message in a channel it can write to.
        """
        if not worker.is_primary:
            return
        me = guild.me
        channel = guild.system_channel
        if not channel or not channel.permissions_for(me).send_messages:
            channel = next((c for c in guild.text_channels if c.permissions_for(me).send_messages), None)
        if channel:
            try:
                await channel.send(
                    "大家好！我是音樂機器人。\n"
                    "1. 先加入一個語音頻道\n"
                    "2. 輸入 `/play` 貼上 Bilibili／YouTube 網址、BV 號，或直接打關鍵字\n"
                    "3. 輸入 `/help` 取得你專屬的網頁控制看板連結（可拖曳排序、調音質）"
                )
            except discord.HTTPException:
                pass
