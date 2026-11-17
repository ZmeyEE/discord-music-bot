"""播放：取串流、開 ffmpeg 送進語音、一首結束後的處理

Playback: fetch the stream, run ffmpeg into voice, and what happens when a song ends
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

import discord

from .. import params
from ..config import target_bitrate
from ..health import StreamProbe, probe_source
from ..sources import Stream, Track, extract_stream_for
from . import audio

if TYPE_CHECKING:
    pass
log = logging.getLogger("musicbot")


class PlaybackMixin:
    async def ensure_playing(self, guild: discord.Guild) -> None:
        """若沒在播且有待播，就取出下一首、取得串流並開始播放；解析失敗會跳下一首

        If nothing is playing and the queue has songs, pop the next one, fetch its stream and start playing.
        A track that fails to resolve is skipped. A per-guild lock prevents two loops running at once.
        """
        st = self.state(guild.id)
        if st.lock.locked():
            return
        async with st.lock:
            while True:
                vc = guild.voice_client
                if vc is None or vc.is_playing() or vc.is_paused() or not st.queue:
                    break
                track = st.queue.popleft()
                st.current, st.stream, st.started_at = track, None, 0.0
                self.notify(guild.id)
                try:
                    stream = await asyncio.to_thread(extract_stream_for, track)   # yt-dlp 會卡住執行緒，所以丟到背景執行緒 / yt-dlp blocks, so run it in a worker thread
                except Exception as exc:  # noqa: BLE001 - 解析失敗就跳下一首 / resolving failed: move on to the next track
                    log.warning("解析失敗 %s: %s", track.url, exc)
                    st.current = None
                    await self._say(st, f"無法播放「{track.title or track.url}」：{str(exc)[:200]}", problem=True)
                    self.notify(guild.id)
                    continue
                vc = guild.voice_client
                if vc is None:  # 載入期間被中斷 / interrupted while loading
                    st.current = None
                    break

                track.title = track.title or stream.title
                track.thumbnail = track.thumbnail or stream.thumbnail
                if track.search and stream.duration:   # Spotify 的歌：進度條要跟實際播的影片一樣長 / a Spotify track: the seek bar must match the video that actually plays
                    track.duration = int(stream.duration)
                else:
                    track.duration = track.duration or (int(stream.duration) if stream.duration else None)
                offset = st.start_offset if st.start_offset_id == track.id else 0.0
                st.start_offset, st.start_offset_id = 0.0, ""
                try:
                    bitrate = self._play_stream(guild, vc, track, stream, offset)
                except Exception as exc:  # noqa: BLE001 - ffmpeg 開不起來、語音剛好斷線等：歌放回最前面，不要讓它憑空消失 / ffmpeg failed to start, voice just dropped...: put the song back at the front instead of losing it
                    log.warning("無法開始播放 %s：%s", track.title or track.url, exc)
                    st.queue.appendleft(track)
                    st.current = None
                    self.notify(guild.id)
                    break
                self.notify(guild.id)
                self._enrich_ahead(guild.id)
                if st.last_announced != track.id:
                    st.last_announced = track.id
                    matched = f"\n對應影片：{track.matched}" if track.matched else ""
                    await self._say(
                        st,
                        f"正在播放：**{track.title}**{matched}\n"
                        f"來源音質 `{stream.quality}` → 傳送 `{'原始音軌直通（不重新編碼）' if st.direct else f'Opus {bitrate}kbps'}`",
                    )
                break

    def _play_stream(
        self, guild: discord.Guild, vc: discord.VoiceClient, track: Track, stream: Stream, offset: float = 0.0
    ) -> int:
        """建立 ffmpeg → Opus 的音訊來源並開始播放（可從 offset 秒開始），回傳實際使用的 Opus 位元率 kbps

        Build the ffmpeg -> Opus audio source and start playing (optionally from ``offset`` seconds).
        Returns the Opus bitrate (kbps) actually used.
        """
        st = self.state(guild.id)
        bitrate = target_bitrate(vc.channel.bitrate // 1000, guild.id)

        def fell_back() -> None:
            """（播放執行緒）直通中途改成重編：更新顯示 / (Player thread) direct playback switched to re-encoding: update what is shown."""
            st.direct, st.bitrate_kbps = False, bitrate
            self.loop.call_soon_threadsafe(self.notify, guild.id)

        # 來源是 Opus 就直通（零損失），否則用音質優先的參數重編一次，細節見 audio.py
        # An Opus source goes direct (zero loss); anything else is re-encoded once with quality-first settings, see audio.py.
        source, st.direct = audio.build(stream, bitrate, offset, self.ffmpeg, fell_back)
        if st.direct:
            bitrate = round(stream.abr) or bitrate
        st.probe = StreamProbe()
        source = probe_source(source, st.probe)     # 只多量測送包時間，內容不變 / only adds packet-timing measurement, content unchanged
        st.current, st.stream, st.bitrate_kbps = track, stream, bitrate
        st.started_at, st.paused_at, st.paused_accum = time.monotonic() - offset, None, 0.0

        def after(err: Exception | None, g: discord.Guild = guild) -> None:
            """播完（或出錯）時由 discord.py 的執行緒呼叫，轉回事件迴圈處理

            Called from discord.py's player thread when playback ends (or fails); hops back to the event loop.
            """
            if err:
                log.error("播放錯誤：%s", err)
            asyncio.run_coroutine_threadsafe(self.on_track_end(g, err), self.loop)

        vc.play(source, after=after)
        log.info(
            "[%s] 播放%s：%s | 來源音質 %s -> %s（頻道設定 %dkbps）",
            self.label, f"（從 {offset:.0f}s）" if offset else "", stream.title, stream.quality,
            "直通，不重新編碼" if st.direct else f"Opus {bitrate}kbps", vc.channel.bitrate // 1000,
        )
        asyncio.create_task(self._voice_check(guild, track.id))
        return bitrate

    def _refill_scope(self, guild: discord.Guild, st) -> None:
        """資料夾循環：待播清單空了就再放一輪（同一個資料夾，或同一層的下一個資料夾）

        Folder loop: when the queue is empty, add another round (the same folder, or the next folder on the same level).
        """
        if not st.scope or st.queue:
            return
        songs = self.hub.library_refill(st.scope)
        if not songs:
            st.scope = None                  # 資料夾已經被刪掉或空了：不再循環 / the folder is gone or empty: stop looping
            return
        st.queue.extend(self.tracks_from_songs(songs[: params.MAX_QUEUE], st.scope["name"], st.scope["avatar"]))
        self.notify(guild.id)

    async def on_track_end(self, guild: discord.Guild, err: Exception | None) -> None:
        """一首歌結束（或被跳過／跳轉）後的善後：處理循環、跳轉，然後播下一首

        Housekeeping after a song ends (or is skipped/seeked): apply loop modes or the pending seek,
        then start the next track.
        """
        st = self.state(guild.id)

        # 拖曳進度條跳轉／切換音質：不是真的播完，而是用新的起點重新開始"同一首"
        # Seeking by dragging the progress bar / changing quality: the song didn't really end; restart "the same one" from a new position.
        if st.pending_seek is not None:
            pos, st.pending_seek = st.pending_seek, None
            vc = guild.voice_client
            if vc and st.current and st.stream:
                try:
                    self._play_stream(guild, vc, st.current, st.stream, pos)
                    if st.seek_paused:
                        vc.pause()
                        st.paused_at = time.monotonic()
                        st.seek_paused = False
                    self.notify(guild.id)
                    return
                except Exception as exc:  # noqa: BLE001
                    log.warning("跳轉失敗：%s", exc)

        track = st.current
        if track and guild.voice_client is None and time.monotonic() - self._gateway_drop < params.RECOVER_WINDOW:
            # 閘道斷線期間語音被 Discord 踢掉：歌放回待播最前面並記住進度，等連線恢復再回頻道接著播
            # Voice was kicked while the gateway was down: put the song back at the front with its position, rejoin once we are back.
            st.start_offset, st.start_offset_id = st.position(), track.id
            st.queue.appendleft(track)
            st.current, st.stream, st.started_at, st.paused_at, st.probe = None, None, 0.0, None, None
            st.skip_flag = st.drop_flag = False
            log.warning("[%s] 語音被 Discord 踢掉（%s），%s 會在連線恢復後接著播", self.label, guild.name, track.title)
            self._start_recover(guild.id)
            self.notify(guild.id)
            return
        played = (time.monotonic() - st.started_at - st.paused_accum) if st.started_at else 0.0
        skipped, st.skip_flag = st.skip_flag, False
        dropped, st.drop_flag = st.drop_flag, False
        st.current, st.stream, st.started_at, st.paused_at, st.probe = None, None, 0.0, None, None
        if track and not dropped:
            healthy = skipped or played >= 2  # 一開始就失敗的曲目不要無限循環 / a track that failed right away must not loop forever
            if st.loop == "queue" and healthy:
                st.queue.append(track)
            elif st.loop == "single" and healthy and not skipped and err is None:
                st.queue.appendleft(track)
        self._refill_scope(guild, st)
        await self.ensure_playing(guild)
        self.notify(guild.id)
