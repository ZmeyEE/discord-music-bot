"""判斷：記錄各時段的卡頓、比較"少一個頻道"的狀態，確定原因後才動作

Judging: keeps stutter per time slice, compares the state with one channel fewer, and acts only once the cause is certain
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .. import params
from .probe import StreamProbe

if TYPE_CHECKING:
    pass

@dataclass
class _Tick:
    """一個 5 秒區間的紀錄 / The record of one 5 s slot."""
    t: float
    k: int            # 這個區間有幾條串流同時在播 / streams playing at the same time in this slot
    dt: float         # 區間長度（秒）/ slot length (s)
    events: int       # 這個區間內全部串流的卡頓事件數 / stutter events over all streams in this slot
    seg: int          # 第幾段（串流數每改變一次就換一段）/ segment number (a new segment starts whenever the stream count changes)
    settled: bool     # 已度過 params.SETTLE（剛改變的前幾秒不計）/ past params.SETTLE (the first seconds after a change are ignored)


@dataclass
class Evidence:
    """判斷成立時附帶的證據（會寫進公告） / The evidence attached when a judgement is confirmed (used in the announcement)."""
    k: int                    # 現在同時播放的串流數 / streams now playing
    age: float                # 最後一個頻道加入多久了 / how long ago the last channel joined
    recent_seconds: float
    recent_events: int
    recent_ticks: int         # 有事件的 5 秒區間數 / number of 5 s slots that had events
    base_seconds: float       # "少一條"時的觀察秒數 / seconds observed in the "one fewer" state
    base_events: int


class Ledger:
    """依"同時播放的串流數"分段記錄卡頓次數，並依上面五條規則做判斷

    Records stutter counts per segment of "number of simultaneously playing streams" and applies the five
    rules from the module docstring in ``judge``.
    """

    def __init__(self) -> None:
        self.ticks: deque[_Tick] = deque()
        self.k: int | None = None
        self.seg = 0
        self.seg_start = 0.0
        self.seg_by_add = False      # 這一段是因為"有頻道加入"開始的（不是因為有頻道離開）/ this segment began because a channel was *added* (not because one left)
        self._last_t: float | None = None

    def add(self, now: float, k: int, events: int) -> None:
        """加入一個區間；串流數改變時開新的一段 / Append one slot; start a new segment when the stream count changed."""
        dt = min(params.CHECK_INTERVAL * 3, now - self._last_t) if self._last_t is not None else params.CHECK_INTERVAL
        self._last_t = now
        if k != self.k:
            self.seg_by_add = self.k is None or k > self.k
            self.k, self.seg, self.seg_start = k, self.seg + 1, now
        self.ticks.append(_Tick(now, k, dt, events, self.seg, now - self.seg_start >= params.SETTLE))
        while self.ticks and now - self.ticks[0].t > params.HISTORY:
            self.ticks.popleft()

    def age(self, now: float) -> float:
        """目前這一段已經持續多久 / How long the current segment has lasted."""
        return now - self.seg_start

    def judge(self, now: float) -> tuple[Evidence | None, str]:
        """要不要怪"最後加入的頻道"？回傳 (證據, 原因代碼)；證據為 None 代表不動作

        Should "the most recently added channel" be blamed? Returns ``(evidence, reason code)``;
        ``evidence is None`` means do nothing. The reason code says which rule stopped us (handy for logs and tests).
        """
        k = self.k or 0
        if k < 2:
            return None, "single"
        if not self.seg_by_add:
            return None, "after-leave"                # 這一段是有頻道離開才開始的：卡頓不是"新加入"造成的 / this segment began with a channel leaving: the stutter wasn't caused by a newcomer
        cur = [t for t in self.ticks if t.seg == self.seg and t.settled and now - t.t <= params.RECENT]
        secs = sum(t.dt for t in cur)
        events = sum(t.events for t in cur)
        hit = [t.t for t in cur if t.events]
        spread = len(hit)
        span = (hit[-1] - hit[0]) if hit else 0.0
        base = [t for t in self.ticks if t.k == k - 1 and t.seg != self.seg and t.settled]
        b_secs, b_events = sum(t.dt for t in base), sum(t.events for t in base)
        ev = Evidence(k, self.age(now), secs, events, spread, b_secs, b_events)
        if secs < params.OBS_MIN:
            return None, "observing"
        if events < params.BAD_EVENTS or events / secs * 60 < params.BAD_RATE:
            return None, "quiet"                      # 偶爾卡一下：濾掉 / an occasional hiccup: filtered out
        if spread < params.BAD_TICKS or span < params.BAD_SPAN:
            return None, "burst"                      # 一次爆發、或卡頓沒有持續一段時間：濾掉 / a single burst, or not sustained long enough: filtered out
        if self.age(now) > params.ATTRIB_WINDOW:
            return None, "late-onset"                 # 不是剛加入的時候才卡：不怪它 / it didn't start right after the join: don't blame the newcomer
        if b_secs < params.BASE_MIN:
            return None, "no-baseline"                # 沒有"少一條"的乾淨對照：無法確定 / no clean "one fewer" reference: can't be sure
        if b_events / b_secs * 60 > params.CLEAN_RATE:
            return None, "baseline-dirty"             # 加入前就在卡：不是新加入的造成的 / it was already stuttering before the join: not the newcomer's fault
        return ev, "confirmed"


@dataclass
class Sample:
    """目前正在播放的一條串流（和 discord 物件分開，方便單元測試）

    One currently playing stream (kept separate from discord objects to make unit tests easy).
    """
    label: str
    channel: str
    since: float                      # 進入這個語音頻道的時間（越大 = 越晚加入）；只用來在同時加入時分先後 / when it entered this voice channel (larger = later); only a tie-breaker for simultaneous joins
    probe: StreamProbe
    latency: float | None = None
    worker: object = None
    guild: object = None
    key: object = None                # 這是哪個（機器人, 伺服器）；歌曲切換時 probe 會換，key 不變 / which (bot, server) this is; the probe changes per song but the key stays


@dataclass
class Removal:
    """偵測器的決定：要停掉哪一條串流，以及理由 / The monitor's decision: which stream to stop, and why."""
    sample: Sample
    remaining: int
    reasons: list[str] = field(default_factory=list)
    evidence: Evidence | None = None
