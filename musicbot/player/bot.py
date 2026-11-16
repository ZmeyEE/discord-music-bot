"""播放器本體：一個 Discord 機器人帳號 = 一個 PlayerBot

同一個機器人帳號在同一個伺服器只能待在一個語音頻道，要多頻道同時播放就加分身（各自一個 PlayerBot），由 Hub 統一協調
功能都拆在同資料夾的檔案裡，這裡只負責把它們組起來和 Discord 事件

The player itself: one Discord bot account = one PlayerBot.

A bot account can sit in one voice channel per server, so more simultaneous channels need clones (one PlayerBot each), all coordinated by the Hub.
The features live in the sibling files; this file only assembles them and handles the Discord events
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from .. import params
from ..config import find_ffmpeg
from . import audio
from .controls import ControlsMixin
from .enqueue import EnqueueMixin
from .playback import PlaybackMixin
from .recover import RecoverMixin
from .snapshot import SnapshotMixin
from .state import GuildState
from .voice import VoiceMixin

if TYPE_CHECKING:
    from ..hub import Hub
log = logging.getLogger("musicbot")


class PlayerBot(VoiceMixin, PlaybackMixin, RecoverMixin, EnqueueMixin, ControlsMixin, SnapshotMixin, discord.Client):
    """一個機器人帳號：負責進語音頻道、解析並播放曲目、維護各伺服器的 GuildState

    One bot account: joins voice channels, resolves and plays tracks, and keeps a GuildState per server.
    The main bot (index 0) also owns the slash-command tree; clones only play audio.
    """
    def __init__(self, hub: "Hub", index: int) -> None:
        super().__init__(intents=discord.Intents.default())
        self.hub = hub
        self.index = index
        self.is_primary = index == 0
        # 斜線指令只註冊在主機器人；分身只負責進語音頻道播放
        # Slash commands are registered on the main bot only; clones just join voice channels and play.
        self.tree = app_commands.CommandTree(self) if self.is_primary else None
        self.states: dict[int, GuildState] = {}
        self.ffmpeg = find_ffmpeg()
        audio.has_resampler(self.ffmpeg, params.RESAMPLER)   # 啟動時先問好 ffmpeg 有沒有 soxr，結果會記住 / ask the ffmpeg build about soxr once at start-up; the answer is remembered
        self._enrich_sem: asyncio.Semaphore | None = None
        self._watch_task: asyncio.Task | None = None
        self._gateway_drop = float("-inf")   # 最近一次閘道斷線的時間（monotonic）/ when the gateway last dropped (monotonic)
        self._recover_tasks: dict[int, asyncio.Task] = {}

    @property
    def pid(self) -> str:
        """播放器識別碼 = 這個機器人帳號的 Discord ID

        Player id = this bot account's Discord id (the front-end uses it to tell players apart).
        """
        return str(self.user.id) if self.user else f"worker{self.index}"

    @property
    def label(self) -> str:
        """顯示名稱（機器人帳號名稱） / Display name (the bot account's name)."""
        return self.user.name if self.user else f"機器人 {self.index + 1}"

    def state(self, guild_id: int) -> GuildState:
        """取得（必要時建立）某伺服器的播放狀態 / Get (creating if needed) the state for a server."""
        return self.states.setdefault(guild_id, GuildState())

    def notify(self, guild_id: int) -> None:
        """通知後台：這個伺服器的狀態變了，請刷新 / Tell the dashboard that this server's state changed."""
        self.hub.notify(guild_id)

    async def setup_hook(self) -> None:
        """登入後、連上閘道前：主機器人同步斜線指令

        Runs after login, before connecting to the gateway: the main bot syncs its slash commands.
        With ``GUILD_ID`` set the commands appear instantly in that server; otherwise they sync globally
        (which Discord may take up to an hour to show).
        """
        if not self.is_primary:
            return
        guild_id = os.environ.get("GUILD_ID", "").strip()
        if guild_id:  # 指定伺服器：指令立即生效 / a specific server: commands take effect immediately
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def on_ready(self) -> None:
        """登入完成：記錄、啟動閒置監看、通知 Hub / Logged in: log it, start the idle watcher and tell the Hub."""
        log.info("已登入：%s（%s）| 伺服器 %d 個", self.user, "主機器人" if self.is_primary else "分身", len(self.guilds))
        if self._watch_task is None:
            self._watch_task = asyncio.create_task(self._watch_idle())
        await self.hub.on_worker_ready(self)

    async def on_disconnect(self) -> None:
        """閘道斷線：記下時間，之後語音被踢掉時才分得出是 Discord 斷線還是人踢的
        Gateway dropped: remember when, so a later voice kick can be told apart (Discord outage vs a human)."""
        self._gateway_drop = time.monotonic()

    async def on_voice_state_update(self, member, before, after) -> None:
        """有人進出語音頻道 / Someone joined or left a voice channel."""
        self.notify(member.guild.id)   # 誰進出頻道會影響"誰能控制"，刷新後台 / who is in a channel affects "who may control", so refresh the dashboard

    async def on_guild_join(self, guild: discord.Guild) -> None:
        """被邀請進新的伺服器 / Invited to a new server."""
        await self.hub.on_guild_join(self, guild)

    async def close(self) -> None:
        """關閉前先取消背景監看 / Cancel the background watcher before closing."""
        if self._watch_task:
            self._watch_task.cancel()
        await super().close()
