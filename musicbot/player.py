"""播放引擎：一個 Discord 機器人帳號 = 一個 PlayerBot

Discord 的限制：同一個機器人帳號在同一個伺服器同時只能待在一個語音頻道
要在同一伺服器的多個頻道同時播放，就需要多個機器人帳號（分身），每個分身各自跑一個 PlayerBot
所有 PlayerBot 由 Hub（hub.py）統一協調

Playback engine: one Discord bot account = one ``PlayerBot``.

Discord's rule: a bot account can sit in only ONE voice channel per server at a time. To play in several
channels of the same server simultaneously you need several bot accounts (clones), each running its own
PlayerBot. All PlayerBots are coordinated by the Hub (hub.py).

Playback pipeline / 播放流程:
  enqueue -> resolve_tracks (sources.py) -> queue -> ensure_playing -> extract_stream -> _play_stream
  (ffmpeg -> Opus -> voice) -> on_track_end -> next track
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import shlex
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from . import config
from .config import find_ffmpeg, target_bitrate
from .health import StreamProbe, probe_source
from .paths import LOG_DIR
from .sources import Stream, Track, enrich_track, extract_stream, resolve_tracks

if TYPE_CHECKING:
    from .hub import Hub

log = logging.getLogger("musicbot")

LOOP_MODES = ("off", "single", "queue")                                   # 循環模式 / loop modes
LOOP_LABEL = {"off": "關閉", "single": "單曲循環", "queue": "列表循環"}   # 顯示名稱 / display names

# 閒置自動離開（秒），分身離開語音頻道後才能被其他頻道接手；設成 0 代表不自動離開
# Idle auto-leave (seconds). A clone can only be taken over by another channel after it leaves; 0 = never leave.
EMPTY_LEAVE_SECONDS = config.env_int("EMPTY_LEAVE_SECONDS", 120)   # 頻道內只剩機器人 / only bots left in the channel
IDLE_LEAVE_SECONDS = config.env_int("IDLE_LEAVE_SECONDS", 300)     # 沒有在播也沒有待播 / nothing playing and nothing queued

_ffmpeg_err = None   # ffmpeg 錯誤輸出的檔案 handle（共用一個）/ the shared file handle for ffmpeg's stderr


def ffmpeg_stderr():
    """ffmpeg 的錯誤輸出寫到 logs/ffmpeg.log，方便排查"沒聲音"

    Send ffmpeg's stderr to ``logs/ffmpeg.log`` to help debug "no sound". The file is reset once it grows past 1 MB.
    """
    global _ffmpeg_err
    if _ffmpeg_err is None:
        LOG_DIR.mkdir(exist_ok=True)
        path = LOG_DIR / "ffmpeg.log"
        if path.exists() and path.stat().st_size > 1_000_000:
            path.unlink()
        _ffmpeg_err = open(path, "ab")
    return _ffmpeg_err


# ============================================================
# 每個伺服器的播放狀態 / Per-guild playback state
# ============================================================
@dataclass
class GuildState:
    """某個機器人帳號在某個伺服器裡的全部播放狀態（待播、目前曲目、進度、閒置計時…）

    All playback state of one bot account inside one server: queue, current track, position, idle timers...
    """
    queue: deque[Track] = field(default_factory=deque)       # 待播清單 / play queue
    current: Track | None = None                              # 正在播放的曲目 / the current track
    stream: Stream | None = None                              # 它的串流（載入中為 None）/ its stream (None while loading)
    bitrate_kbps: int = 0
    loop: str = "off"
    text_channel_id: int | None = None                        # 公告要發到哪個文字頻道 / text channel for announcements
    last_voice_id: int | None = None
    started_at: float = 0.0                                   # 用來算播放位置 / used to compute the position
    paused_at: float | None = None
    paused_accum: float = 0.0
    skip_flag: bool = False
    drop_flag: bool = False             # 目前這首被使用者"刪除"：不論循環模式都不要再排回去 / the current track was "deleted" by the user: never re-queue it, whatever the loop mode
    last_announced: str = ""
    last_dave_warn: str = ""
    pending_seek: float | None = None   # 使用者拖曳進度條後要跳到的秒數 / seconds to jump to after the user dragged the progress bar
    seek_paused: bool = False           # 跳轉前是否處於暫停（跳完要維持暫停）/ whether it was paused before seeking (stay paused afterwards)
    empty_since: float = 0.0            # 頻道內只剩機器人的起始時間（monotonic）/ since when only bots remain in the channel (monotonic clock)
    idle_since: float = 0.0             # 沒有在播也沒有待播的起始時間 / since when nothing is playing or queued
    reserved_channel: int | None = None  # 已被預約要去的語音頻道（避免兩個人同時加歌時搶到同一個分身）/ the voice channel this clone is reserved for (stops two people grabbing the same clone at once)
    reserved_until: float = 0.0
    probe: StreamProbe | None = None    # 這首歌的送包時間紀錄（播放健康偵測用，見 health.py）/ packet-timing record of this song (for health.py)
    joined_at: float = 0.0              # 這個機器人進入目前語音頻道的時間（monotonic）；卡頓時依此找出"最後加入的"/ when this bot entered its current voice channel (monotonic); used to find "the newest" on stutter
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)   # 防止同時啟動兩次播放 / prevents starting playback twice concurrently

    @property
    def reserved(self) -> bool:
        """預約是否仍有效 / Whether the reservation is still valid."""
        return time.monotonic() < self.reserved_until

    def position(self) -> float:
        """目前播放到第幾秒（扣掉暫停的時間） / Current playback position in seconds (paused time excluded)."""
        if not self.started_at:
            return 0.0
        ref = self.paused_at if self.paused_at is not None else time.monotonic()
        return max(0.0, ref - self.started_at - self.paused_accum)

    @property
    def busy(self) -> bool:
        """有在播、有待播、或已被預約（分身被占用）

        Playing, has queued songs, or reserved (i.e. this clone is occupied).
        """
        return bool(self.current or self.queue or self.reserved)


# ============================================================
# 播放器本體 / The player itself
# ============================================================
class PlayerBot(discord.Client):
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
        self._enrich_sem: asyncio.Semaphore | None = None
        self._watch_task: asyncio.Task | None = None

    # ------------------------------------------------------------
    # 基礎 / Basics
    # ------------------------------------------------------------
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

    # ------------------------------------------------------------
    # Discord 事件 / Discord events
    # ------------------------------------------------------------
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

    # ------------------------------------------------------------
    # 語音與播放 / Voice and playback
    # ------------------------------------------------------------
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

    async def _say(self, st: GuildState, text: str) -> None:
        """在記錄的文字頻道發訊息；失敗就算了 / Post a message in the remembered text channel; failures are ignored."""
        if not st.text_channel_id:
            return
        ch = self.get_channel(st.text_channel_id)
        if ch:
            try:
                await ch.send(text)
            except discord.HTTPException:
                pass

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
                    stream = await asyncio.to_thread(extract_stream, track.url)   # yt-dlp 會卡住執行緒，所以丟到背景執行緒 / yt-dlp blocks, so run it in a worker thread
                except Exception as exc:  # noqa: BLE001 - 解析失敗就跳下一首 / resolving failed: move on to the next track
                    log.warning("解析失敗 %s: %s", track.url, exc)
                    st.current = None
                    await self._say(st, f"無法播放「{track.title or track.url}」：{str(exc)[:200]}")
                    self.notify(guild.id)
                    continue
                vc = guild.voice_client
                if vc is None:  # 載入期間被中斷 / interrupted while loading
                    st.current = None
                    break

                track.title = track.title or stream.title
                track.thumbnail = track.thumbnail or stream.thumbnail
                track.duration = track.duration or (int(stream.duration) if stream.duration else None)
                bitrate = self._play_stream(guild, vc, track, stream)
                self.notify(guild.id)
                if st.last_announced != track.id:
                    st.last_announced = track.id
                    await self._say(
                        st,
                        f"正在播放：**{track.title}**\n"
                        f"來源音質 `{stream.quality}` → 傳送 `Opus {bitrate}kbps`",
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
        header_blob = "".join(f"{k}: {v}\r\n" for k, v in stream.headers.items())
        seek = f"-ss {offset:.2f} " if offset > 0 else ""   # -ss 放在 -i 之前 = 快速跳轉 / -ss before -i = fast seek
        before = (
            f"{seek}-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "   # 網路斷線時自動重連 / auto-reconnect on network hiccups
            f"-headers {shlex.quote(header_blob)}"
        )
        # codec 不給 -> discord.py 以 libopus 重新編碼
        # No codec given -> discord.py re-encodes with libopus at the bitrate we pass.
        source = discord.FFmpegOpusAudio(
            stream.url, bitrate=bitrate, executable=self.ffmpeg, before_options=before,
            options="-vn", stderr=ffmpeg_stderr(),
        )
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
            "[%s] 播放%s：%s | 來源音質 %s -> Opus %dkbps（頻道設定 %dkbps）",
            self.label, f"（從 {offset:.0f}s）" if offset else "", stream.title, stream.quality, bitrate,
            vc.channel.bitrate // 1000,
        )
        asyncio.create_task(self._voice_check(guild, track.id))
        return bitrate

    async def _voice_check(self, guild: discord.Guild, track_id: str) -> None:
        """開始播放幾秒後檢查語音連線／端對端加密（DAVE）狀態，寫進記錄；沒就緒時提醒使用者

        A few seconds after playback starts, inspect the voice connection and the end-to-end encryption
        (DAVE) state, write them to the log, and warn the users if DAVE isn't ready (a classic cause of "silent bot").
        """
        for waited, final in ((4, False), (16, True)):   # 播放後 4 秒、20 秒各檢查一次 / checks at 4 s and 20 s after playback starts
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
                    )
            except Exception as exc:  # noqa: BLE001
                log.warning("語音診斷失敗：%s", exc)
                return

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
        await self.ensure_playing(guild)
        self.notify(guild.id)

    async def enrich_many(self, guild_id: int, tracks: list[Track]) -> None:
        """在背景補齊多首曲目的縮圖等資訊（同時最多 3 個，免得被站方限流）

        Fill in thumbnails etc. for many tracks in the background (at most 3 at a time to avoid rate limits).
        """
        if self._enrich_sem is None:
            self._enrich_sem = asyncio.Semaphore(3)

        async def one(t: Track) -> None:
            async with self._enrich_sem:
                await asyncio.to_thread(enrich_track, t)
            self.notify(guild_id)

        await asyncio.gather(*(one(t) for t in tracks))

    # ------------------------------------------------------------
    # 閒置自動離開 / Idle auto-leave
    # ------------------------------------------------------------
    async def _watch_idle(self) -> None:
        """頻道沒人、或太久沒在播，就自動離開，讓這個分身可以被別的頻道接手

        Leave automatically when the channel is empty or nothing has played for too long, so this clone
        becomes available to other channels. Wakes every 20 s.
        """
        while True:
            await asyncio.sleep(20)
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
                if EMPTY_LEAVE_SECONDS and st.empty_since and now - st.empty_since >= EMPTY_LEAVE_SECONDS:
                    reason = "頻道內沒有人了"
                elif IDLE_LEAVE_SECONDS and st.idle_since and now - st.idle_since >= IDLE_LEAVE_SECONDS:
                    reason = "已經很久沒有播放"
                if reason:
                    log.info("[%s] %s，自動離開語音頻道（%s）", self.label, reason, guild.name)
                    await self._say(st, f"{reason}，我先離開語音頻道了。要繼續聽請再用 `/play`。")
                    await self.stop(guild)

    # ------------------------------------------------------------
    # 預約 / Reservation
    # ------------------------------------------------------------
    # 挑到這個分身的瞬間就登記，解析網址要幾秒，期間不能被別人搶走
    # Registered the moment this clone is picked: resolving a URL takes seconds, and nobody else may grab it meanwhile.
    def reserve(self, guild_id: int, channel_id: int, seconds: float = 60.0) -> None:
        """預約這個分身要去的頻道（預設 60 秒） / Reserve this clone for a channel (60 s by default)."""
        st = self.state(guild_id)
        st.reserved_channel, st.reserved_until = channel_id, time.monotonic() + seconds

    def release(self, guild_id: int) -> None:
        """解除預約 / Cancel the reservation."""
        st = self.state(guild_id)
        st.reserved_channel, st.reserved_until = None, 0.0

    # ------------------------------------------------------------
    # 操作（Discord 指令與網頁後台共用）/ Actions (shared by Discord commands and the web dashboard)
    # ------------------------------------------------------------
    async def enqueue(
        self, guild: discord.Guild, query: str, requester: str,
        voice_channel: discord.abc.Connectable | None = None, when: str = "end", requester_avatar: str = "",
    ) -> tuple[list[Track], str | None]:
        """加入曲目，when：end 加到最後｜next 下一首播放｜now 立刻播放
        回傳 (加入的曲目, 提示訊息)，提示訊息非 None 代表有問題需告知使用者

        Add tracks. ``when``: ``end`` = append | ``next`` = play next | ``now`` = play immediately.
        Returns ``(added tracks, message)``; a non-None message means something needs telling the user.
        """
        try:
            return await self._enqueue(guild, query, requester, voice_channel, when, requester_avatar)
        finally:
            self.release(guild.id)   # 不論成功失敗，都解除預約 / release the reservation either way

    async def _enqueue(
        self, guild: discord.Guild, query: str, requester: str,
        voice_channel: discord.abc.Connectable | None, when: str, requester_avatar: str = "",
    ) -> tuple[list[Track], str | None]:
        """enqueue 的實作：解析 → 放進佇列 → 補資訊 → 進語音頻道 → 開始播

        The body of enqueue: resolve -> put into the queue -> enrich -> join voice -> start playing.
        """
        try:
            tracks = await asyncio.to_thread(resolve_tracks, query, requester)
        except Exception as exc:  # noqa: BLE001
            return [], f"解析失敗：{str(exc)[:200]}"
        if not tracks:
            return [], "找不到可播放的內容"
        for t in tracks:      # 每次都明確指定（包含空字串），避免沿用快取裡上一位點歌者的頭像 / always set it explicitly (even ""), so a cached result doesn't keep the previous requester's avatar
            t.requester_avatar = requester_avatar
        st = self.state(guild.id)
        if when == "end":
            st.queue.extend(tracks)
        else:
            st.queue.extendleft(reversed(tracks))   # 保持多首的原順序，整批插到最前面 / keep the original order of multiple tracks while inserting them at the front
        self.notify(guild.id)
        if len(tracks) == 1:
            if not tracks[0].thumbnail or not tracks[0].title:
                await asyncio.to_thread(enrich_track, tracks[0])
        else:
            pending = [t for t in tracks if not t.thumbnail]
            if pending:
                asyncio.create_task(self.enrich_many(guild.id, pending))
        self.notify(guild.id)
        try:
            vc = await self.ensure_voice(guild, voice_channel)
        except Exception as exc:  # noqa: BLE001
            return tracks, f"已加入待播清單，但無法進入語音頻道：{str(exc)[:120]}"
        if vc is None:
            return tracks, "已加入待播清單，但機器人還不在語音頻道：請先在 Discord 使用 /join"
        if when == "now" and (vc.is_playing() or vc.is_paused()):
            self.skip(guild)                         # 跳過目前這首，換成剛插到最前面的 / skip the current song so the one just inserted at the front plays
        else:
            await self.ensure_playing(guild)
        return tracks, None

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

    # ------------------------------------------------------------
    # 狀態快照 / State snapshot
    # ------------------------------------------------------------
    # 單一播放器；權限與多播放器資訊由 Hub 加上
    # For a single player; permissions and multi-player info are added by the Hub.
    def player_state(self, guild: discord.Guild) -> dict:
        """這個播放器在該伺服器的狀態，整理成可送給前端的字典

        This player's state in a server as a dict ready to send to the front-end.
        """
        st = self.state(guild.id)
        vc = guild.voice_client
        cur = None
        if st.current:
            cur = st.current.public() | {
                "quality": st.stream.quality if st.stream else "",
                "bitrate": st.bitrate_kbps,
                "position": round(st.position(), 1),
                "loading": st.stream is None,
            }
        return {
            "connected": bool(vc),
            "channel": vc.channel.name if vc else None,
            "paused": bool(vc and vc.is_paused()),
            "loop": st.loop,
            "current": cur,
            "queue": [t.public() for t in st.queue],
        }
