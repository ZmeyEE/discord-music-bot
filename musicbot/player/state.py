"""每個伺服器的播放狀態（待播、目前曲目、進度、閒置計時…）

Per-server playback state: queue, current track, position, idle timers...
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..health import StreamProbe
from ..paths import LOG_DIR
from ..sources import Stream, Track

if TYPE_CHECKING:
    pass


LOOP_MODES = ("off", "single", "queue")                                   # 循環模式 / loop modes
LOOP_LABEL = {"off": "關閉", "single": "單曲循環", "queue": "列表循環"}   # 顯示名稱 / display names

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


@dataclass
class GuildState:
    """某個機器人帳號在某個伺服器裡的全部播放狀態（待播、目前曲目、進度、閒置計時…）

    All playback state of one bot account inside one server: queue, current track, position, idle timers...
    """
    queue: deque[Track] = field(default_factory=deque)       # 待播清單 / play queue
    current: Track | None = None                              # 正在播放的曲目 / the current track
    stream: Stream | None = None                              # 它的串流（載入中為 None）/ its stream (None while loading)
    bitrate_kbps: int = 0
    scope: dict | None = None            # 資料夾循環：{mode: folder|folders, user, node, name, avatar}；待播清單播完就再放一輪 / folder loop: when the queue runs out another round is added
    direct: bool = False                                      # 這首是不是直通（來源是 Opus，沒有重新編碼）/ is this song sent direct (an Opus source, not re-encoded)
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
    stale_since: float = 0.0            # 語音物件在但沒連上的起始時間 / since when the voice object has been there but not connected
    idle_since: float = 0.0             # 沒有在播也沒有待播的起始時間 / since when nothing is playing or queued
    reserved_channel: int | None = None  # 已被預約要去的語音頻道（避免兩個人同時加歌時搶到同一個分身）/ the voice channel this clone is reserved for (stops two people grabbing the same clone at once)
    reserved_until: float = 0.0
    probe: StreamProbe | None = None    # 這首歌的送包時間紀錄（播放健康偵測用，見 health.py）/ packet-timing record of this song (for health.py)
    joined_at: float = 0.0              # 這個機器人進入目前語音頻道的時間（monotonic）；卡頓時依此找出"最後加入的"/ when this bot entered its current voice channel (monotonic); used to find "the newest" on stutter
    start_offset: float = 0.0           # 斷線救回的那首要從第幾秒接著播 / where the rescued track resumes after a drop
    start_offset_id: str = ""           # 上面那個秒數屬於哪一首（id 對不上就不套用）/ which track that offset belongs to (ignored when the id differs)
    recovering: bool = False            # 正在回語音頻道 / rejoining voice right now
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
