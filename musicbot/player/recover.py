"""斷線救援：語音被 Discord 踢掉後，連線恢復就回頻道接著播

Outage recovery: after Discord kicks us from voice, rejoin once connected and carry on
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from .. import params

if TYPE_CHECKING:
    pass
log = logging.getLogger("musicbot")


class RecoverMixin:
    def _start_recover(self, guild_id: int) -> None:
        """開一個背景工作回語音頻道，同一個伺服器只會有一個
        Start the background job that rejoins voice; only one per server."""
        st = self.state(guild_id)
        if st.recovering:
            return
        st.recovering = True
        self._recover_tasks[guild_id] = asyncio.create_task(self._recover_voice(guild_id))

    async def _recover_voice(self, guild_id: int) -> None:
        """連線恢復後回到原本的語音頻道，接著播剛剛被中斷的那首
        等待時間 3 秒起每次加倍，最多 30 秒；頻道沒有真人就繼續等，使用者 /stop 或超過 params.RECOVER_SECONDS 就放棄

        Rejoin the old voice channel once we are connected again and carry on with the interrupted song.
        Waits 3 s, doubling up to 30 s; with nobody in the channel it keeps waiting. Gives up on /stop or after params.RECOVER_SECONDS.
        """
        st = self.state(guild_id)
        deadline, delay = time.monotonic() + params.RECOVER_SECONDS, params.RECOVER_FIRST_DELAY
        try:
            while time.monotonic() < deadline and st.recovering:
                await asyncio.sleep(delay)
                delay = min(delay * 2, params.RECOVER_MAX_DELAY)
                guild = self.get_guild(guild_id)
                if guild is None or self.is_closed():
                    return
                if not self.is_ready() or not st.queue:
                    continue
                channel = guild.get_channel(st.last_voice_id) if st.last_voice_id else None
                if channel is None:
                    return
                if guild.voice_client is None and not [m for m in channel.members if not m.bot]:
                    continue
                try:
                    await self.ensure_voice(guild)
                    await self.ensure_playing(guild)
                except Exception as exc:  # noqa: BLE001 - 還沒連好就下一輪再試 / not connected yet: try again next round
                    log.warning("[%s] 回語音頻道失敗，稍後再試：%s", self.label, str(exc)[:120])
                    continue
                if guild.voice_client is not None:
                    log.info("[%s] 已回到語音頻道並接著播（%s）", self.label, guild.name)
                    await self._say(st, "剛剛連線中斷，我回來了，接著播剛才那首")
                    return
        finally:
            st.recovering = False
            self._recover_tasks.pop(guild_id, None)
            self.notify(guild_id)
