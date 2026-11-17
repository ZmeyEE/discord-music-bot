"""語音頻道：進出、發訊息、連線診斷、閒置自動離開、預約

Voice channel: join / leave, announcements, connection diagnostics, idle auto-leave, reservation
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

import discord

from .. import params
from .state import GuildState

if TYPE_CHECKING:
    pass
log = logging.getLogger("musicbot")


class VoiceMixin:
    async def ensure_voice(self, guild: discord.Guild, channel: discord.abc.Connectable | None = None):
        """確保已在語音頻道：指定 channel 就進去／移過去；沒指定就回到上次的頻道

        Make sure we are in a voice channel: join/move to ``channel`` when given, otherwise return to the
        last channel used. Returns the voice client, or None if there is nowhere to go.
        """
        st = self.state(guild.id)
        vc = guild.voice_client
        if channel is not None:
            st.last_voice_id = channel.id
            if vc is None:
                vc = await channel.connect()
                st.joined_at = time.monotonic()
            elif vc.channel != channel:
                await vc.move_to(channel)
                st.joined_at = time.monotonic()
            return vc
        if vc:
            return vc
        ch = guild.get_channel(st.last_voice_id) if st.last_voice_id else None
        if not ch:
            return None
        vc = await ch.connect()
        st.joined_at = time.monotonic()
        return vc

    async def _say(self, st: GuildState, text: str, problem: bool = False) -> None:
        """在記錄的文字頻道發訊息；失敗就算了，problem=True 表示在回報問題（要不要發由 params.CHANNEL_NOTICES 決定）

        Post a message in the remembered text channel; failures are ignored. ``problem=True`` marks a report of something
        that went wrong; whether it is posted at all is decided by params.CHANNEL_NOTICES.
        """
        if not st.text_channel_id or not params.notices_allow(problem):
            return
        ch = self.get_channel(st.text_channel_id)
        if ch:
            try:
                await ch.send(text)
            except discord.HTTPException:
                pass

    async def _voice_check(self, guild: discord.Guild, track_id: str) -> None:
        """開始播放幾秒後檢查語音連線／端對端加密（DAVE）狀態，寫進記錄；沒就緒時提醒使用者

        A few seconds after playback starts, inspect the voice connection and the end-to-end encryption
        (DAVE) state, write them to the log, and warn the users if DAVE isn't ready (a classic cause of "silent bot").
        """
        checks = params.VOICE_CHECK_DELAYS
        for waited, final in ((checks[0], False), (checks[1], True)):   # 播放後 4 秒、20 秒各檢查一次 / checks at 4 s and 20 s after playback starts
            await asyncio.sleep(waited)
            st, vc = self.state(guild.id), guild.voice_client
            if vc is None or st.current is None or st.current.id != track_id:
                return
            try:
                conn = vc._connection  # noqa: SLF001 - discord.py 沒有公開 API，只用來診斷 / discord.py has no public API for this; diagnostics only
                dave = conn.dave_session
                ready = bool(dave and dave.ready)
                version = getattr(conn, "dave_protocol_version", "?")
                log.info(
                    "[%s] 語音診斷：connected=%s playing=%s members=%d dave_version=%s dave_ready=%s latency=%.0fms",
                    self.label, vc.is_connected(), vc.is_playing(), len(vc.channel.members), version, ready,
                    vc.latency * 1000,
                )
                if final and version not in (0, "?") and not ready and st.last_dave_warn != track_id:
                    st.last_dave_warn = track_id
                    await self._say(
                        st,
                        "語音端對端加密（DAVE）尚未就緒，頻道內的人可能聽不到聲音。"
                        "請試著 `/stop` 後再 `/play`，並確認 Discord 客戶端是最新版。",
                        problem=True,
                    )
            except Exception as exc:  # noqa: BLE001
                log.warning("語音診斷失敗：%s", exc)
                return

    async def _watch_idle(self) -> None:
        """頻道沒人、或太久沒在播，就自動離開，讓這個分身可以被別的頻道接手

        Leave automatically when the channel is empty or nothing has played for too long, so this clone
        becomes available to other channels. Wakes every 20 s.
        """
        while True:
            await asyncio.sleep(params.IDLE_CHECK_SECONDS)
            try:
                await self._idle_round()
            except Exception:  # noqa: BLE001 - 這個監看迴圈死掉就再也不會自動離開頻道，所以任何錯誤都只記錄 / if this loop died nothing would ever leave a channel again, so any error is only logged
                log.exception("閒置檢查出錯，下一輪再試")

    async def _idle_round(self) -> None:
        """檢查一輪所有伺服器 / One pass over all servers."""
        now = time.monotonic()
        for guild in list(self.guilds):
            vc, st = guild.voice_client, self.state(guild.id)
            if not vc:
                st.empty_since = st.idle_since = 0.0
                continue
            humans = [m for m in vc.channel.members if not m.bot]
            st.empty_since = (st.empty_since or now) if not humans else 0.0
            busy = vc.is_playing() or vc.is_paused() or st.busy
            st.idle_since = (st.idle_since or now) if not busy else 0.0

            reason = None
            if params.EMPTY_LEAVE_SECONDS and st.empty_since and now - st.empty_since >= params.EMPTY_LEAVE_SECONDS:
                reason = "頻道內沒有人了"
            elif params.IDLE_LEAVE_SECONDS and st.idle_since and now - st.idle_since >= params.IDLE_LEAVE_SECONDS:
                reason = "已經很久沒有播放"
            if reason:
                log.info("[%s] %s，自動離開語音頻道（%s）", self.label, reason, guild.name)
                await self._say(st, f"{reason}，我先離開語音頻道了。要繼續聽請再用 `/play`。")
                await self.stop(guild)

    # 挑到這個分身的瞬間就登記，解析網址要幾秒，期間不能被別人搶走
    # Registered the moment this clone is picked: resolving a URL takes seconds, and nobody else may grab it meanwhile.
    def reserve(self, guild_id: int, channel_id: int, seconds: float = params.RESERVE_SECONDS) -> None:
        """預約這個分身要去的頻道（預設 60 秒） / Reserve this clone for a channel (60 s by default)."""
        st = self.state(guild_id)
        st.reserved_channel, st.reserved_until = channel_id, time.monotonic() + seconds

    def release(self, guild_id: int) -> None:
        """解除預約 / Cancel the reservation."""
        st = self.state(guild_id)
        st.reserved_channel, st.reserved_until = None, 0.0
