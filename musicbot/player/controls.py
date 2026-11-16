"""播放控制：跳過、跳轉、暫停、停止、循環、排序、刪除

Playback controls: skip, seek, pause, stop, loop, reorder, remove
"""
from __future__ import annotations

import random
import time
from collections import deque
from typing import TYPE_CHECKING

import discord

from .state import LOOP_MODES

if TYPE_CHECKING:
    pass


class ControlsMixin:
    def skip(self, guild: discord.Guild) -> bool:
        """跳過目前這首；有東西可跳回傳 True / Skip the current song; returns True if there was something to skip."""
        vc = guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            self.state(guild.id).skip_flag = True
            vc.stop()
            return True
        return False

    def seek(self, guild: discord.Guild, position: float) -> bool:
        """跳到目前曲目的 position 秒，ffmpeg 要重新開始，所以先停掉再由 on_track_end 以新起點重播

        Jump to ``position`` seconds of the current track. ffmpeg has to restart, so we stop it and let
        ``on_track_end`` replay from the new start point.
        """
        vc, st = guild.voice_client, self.state(guild.id)
        if not (vc and st.current and st.stream and (vc.is_playing() or vc.is_paused())):
            return False
        limit = (st.current.duration - 1) if st.current.duration else position
        st.pending_seek = max(0.0, min(float(position), float(limit)))
        st.seek_paused = vc.is_paused()      # 暫停中跳轉：跳完維持暫停 / seeking while paused: stay paused afterwards
        vc.stop()
        return True

    def restart_current(self, guild: discord.Guild) -> None:
        """從目前位置重新開始這首（切換音質後讓新位元率立刻生效）

        Restart the current song from where it is (so a new bitrate takes effect right after a quality change).
        """
        st = self.state(guild.id)
        if st.current and st.stream:
            self.seek(guild, st.position())

    def pause(self, guild: discord.Guild) -> bool:
        """暫停；成功回傳 True / Pause; returns True on success."""
        vc, st = guild.voice_client, self.state(guild.id)
        if vc and vc.is_playing():
            vc.pause()
            st.paused_at = time.monotonic()
            self.notify(guild.id)
            return True
        return False

    def resume(self, guild: discord.Guild) -> bool:
        """繼續；同時把暫停的時間累計起來，位置才會算對 / Resume; also accumulates the paused time so the position stays right."""
        vc, st = guild.voice_client, self.state(guild.id)
        if vc and vc.is_paused():
            vc.resume()
            if st.paused_at is not None:
                st.paused_accum += time.monotonic() - st.paused_at
                st.paused_at = None
            self.notify(guild.id)
            return True
        return False

    async def stop(self, guild: discord.Guild) -> None:
        """停止、清空待播並離開語音頻道（釋放這個分身） / Stop, clear the queue and leave voice (frees this clone)."""
        st = self.state(guild.id)
        st.queue.clear()
        st.current, st.stream, st.started_at, st.paused_at, st.probe = None, None, 0.0, None, None
        st.empty_since = st.idle_since = 0.0
        st.joined_at = 0.0
        st.recovering = False            # 使用者主動停止：不要再自動回頻道 / the user stopped it: no more auto-rejoin
        st.start_offset, st.start_offset_id = 0.0, ""
        vc = guild.voice_client
        if vc:
            vc.stop()
            await vc.disconnect()
        self.notify(guild.id)

    def set_loop(self, guild_id: int, mode: str) -> None:
        """設定循環模式（只接受 LOOP_MODES 裡的值） / Set the loop mode (only values in LOOP_MODES are accepted)."""
        if mode in LOOP_MODES:
            self.state(guild_id).loop = mode
            self.notify(guild_id)

    def move_track(self, guild_id: int, track_id: str, index: int) -> None:
        """把待播的某一首移到新的位置（拖曳排序） / Move a queued track to a new position (drag-and-drop ordering)."""
        st = self.state(guild_id)
        t = next((x for x in st.queue if x.id == track_id), None)
        if t:
            st.queue.remove(t)
            st.queue.insert(max(0, min(index, len(st.queue))), t)
        self.notify(guild_id)

    def remove_track(self, guild_id: int, track_id: str) -> None:
        """從待播清單刪除一首 / Remove one track from the queue."""
        st = self.state(guild_id)
        t = next((x for x in st.queue if x.id == track_id), None)
        if t:
            st.queue.remove(t)
        self.notify(guild_id)

    async def play_now(self, guild: discord.Guild, track_id: str) -> None:
        """把待播的某一首插到最前面並立刻播放 / Move a queued track to the front and play it right away."""
        st = self.state(guild.id)
        t = next((x for x in st.queue if x.id == track_id), None)
        if not t:
            return
        st.queue.remove(t)
        st.queue.appendleft(t)
        if not self.skip(guild):
            await self.ensure_playing(guild)
        self.notify(guild.id)

    def shuffle(self, guild_id: int) -> None:
        """隨機打亂待播清單 / Shuffle the queue."""
        st = self.state(guild_id)
        items = list(st.queue)
        random.shuffle(items)
        st.queue = deque(items)
        self.notify(guild_id)

    def remove_current(self, guild: discord.Guild) -> None:
        """把"正在播放"刪掉：跳到下一首，且這首不再被循環排回去

        Delete the song that is playing: skip to the next one, and never re-queue it through a loop mode.
        """
        st = self.state(guild.id)
        st.drop_flag = True
        if not self.skip(guild):
            st.drop_flag = False

    def clear_queue(self, guild_id: int) -> None:
        """清空待播清單（不影響正在播的這首） / Clear the queue (the song currently playing is unaffected)."""
        self.state(guild_id).queue.clear()
        self.notify(guild_id)
