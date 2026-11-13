"""播放健康偵測：不干擾播放，只在背景"聽"有沒有卡頓；確定是新加入的頻道造成的，就從最後加入的開始，一個一個停掉並公告

分身沒有數量上限；這個偵測器就是把關的人

怎麼不影響播放
- 音訊來源包一層薄薄的"探針"（ProbedSource）：每 20 ms 讀一次封包時只多記錄兩個時間戳，沒有鎖、沒有 I/O
- 偵測器是獨立的背景工作，每 5 秒醒來一次，只讀計數、做幾個加減乘除，它自己不碰語音連線，
  只有"確定要停某個頻道"那一刻才會動作

怎麼判斷"卡頓"
- 正常情況下相鄰兩次讀取相隔約 20 ms，超過 60 ms（README 實測的可聞門檻）就記一次事件；
  間隔超過 1.5 秒是暫停／跳轉，開播前 3 秒是 ffmpeg 暖機，都不算

怎麼避免誤殺（濾波＋歸因＋緩衝）——要"全部"成立才會停掉頻道：
1. 持續：最近 60 秒內至少 4 次事件、分散在至少 3 個不同的 5 秒區間、第一次到最後一次相隔至少 20 秒，
   而且每分鐘 ≥ 6 次，偶爾一次、或一次同時爆出一堆（磁碟／GC 的瞬間卡頓）、或只卡短短一陣都不算
2. 加入前是順的：目前這個"同時播放 N 條"的狀態之前，"N−1 條"的狀態至少觀察過 40 秒，而且很乾淨（每分鐘 ≤ 1.5 次）
3. 加入後才卡的：卡頓在最後一個頻道加入後 5 分鐘內出現（之後才出現的卡頓更可能是電腦別的程式造成的，不怪它）
4. 緩衝：停掉一個之後至少隔 90 秒才會再判斷；而且"因為有頻道離開才開始的狀態"不會再被怪罪——
   停掉一個之後如果還是卡，就代表原因不在新加入的頻道（例如你同時開了遊戲），不會繼續停；
   要等下一次又有新頻道加入，才會重新判斷，所以不可能因為一次卡頓把頻道全部停光，永遠至少保留 1 個頻道
5. 停掉之後 10 分鐘內不再派新的頻道進來（避免剛停掉又馬上加回去、再卡一次）

Playback health monitor: it never interferes with playback; it just "listens" in the background for stutter.
When it is certain that a newly added channel caused it, it stops channels one at a time, newest first,
and announces each removal.

Clones have no upper limit; this monitor is the gatekeeper.

How it stays out of the way
- The audio source is wrapped in a thin "probe" (ProbedSource): each 20 ms packet read only records two
  timestamps. No locks, no I/O.
- The monitor is a separate background task that wakes every 5 s, reads counters and does a little
  arithmetic. It never touches voice connections itself, except at the moment it decides to stop a channel.

How a "stutter" is defined
- Normally two consecutive reads are ~20 ms apart. A gap above 60 ms (the audible threshold measured in the
  README) counts as one event. Gaps above 1.5 s mean pause/seek, and the first 3 s of a song is ffmpeg
  warm-up; neither counts.

How wrongful removals are avoided (filtering + attribution + buffering) - ALL of these must hold:
1. Sustained: >= 4 events in the last 60 s, spread over >= 3 different 5 s slots, first-to-last event >= 20 s
   apart, and >= 6 events per minute. A one-off, a single burst (disk / GC hiccup) or a short blip doesn't count.
2. Smooth before: before the current "N streams playing" state, the "N-1 streams" state was observed for
   >= 40 s and was clean (<= 1.5 events per minute).
3. Stutter after joining: it started within 5 minutes of the last channel joining (later stutter is more
   likely caused by other programs on the PC, so the newcomer isn't blamed).
4. Buffering: after one removal, wait >= 90 s before judging again; and a state that began because a channel
   *left* is never blamed - if it still stutters after a removal, the cause isn't the newcomer (maybe you
   launched a game), so it stops removing until another channel joins. A single hiccup therefore can never
   wipe out all channels. At least 1 channel is always kept.
5. For 10 minutes after a removal no new channel is assigned (avoids re-adding it straight away and stuttering again).
"""
from __future__ import annotations

import asyncio
import ctypes
import logging
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from .hub import Hub

log = logging.getLogger("musicbot")

# ============================================================
# 參數 / Tunable parameters
# ============================================================
# ---- 事件偵測（探針）/ event detection (the probe) ----
LATE_GAP = 0.060          # 相鄰兩次讀取相隔超過這個秒數 = 一次卡頓事件 / gap between two reads above this = one stutter event
STARVE_READ = 0.040       # 單次讀取 ffmpeg 超過這個秒數 = 來源／編碼跟不上 / a single ffmpeg read slower than this = source/encoder can't keep up
RESUME_GAP = 1.5          # 間隔超過這個秒數 = 暫停／跳轉後恢復，不是卡頓 / a gap longer than this = resumed after pause/seek, not a stutter
WARMUP = 3.0              # 開播前幾秒是 ffmpeg 暖機，不計 / the first seconds of a song are ffmpeg warm-up and are ignored

# ---- 判斷（濾波＋歸因＋緩衝）/ judgement (filtering + attribution + buffering) ----
CHECK_INTERVAL = 5.0
SETTLE = 8.0              # 串流數剛改變後，前幾秒（新串流暖機、連線建立）不計入觀察 / right after the stream count changes, ignore a few seconds (warm-up, connection set-up)
RECENT = 60.0             # "現在的狀況"看最近這麼多秒 / how many recent seconds describe "the current situation"
OBS_MIN = 30.0            # 現在這個狀態至少要觀察這麼久才下判斷 / the current state must be observed this long before judging
BASE_MIN = 40.0           # "少一條"的狀態至少要觀察過這麼久，才能當作乾淨的對照 / the "one fewer" state must have been observed this long to serve as a clean baseline
BAD_EVENTS = 4            # 最近 RECENT 秒內至少幾次事件 / at least this many events within RECENT seconds
BAD_TICKS = 3             # ……而且分散在至少幾個不同的 5 秒區間（排除一次爆發）/ ...spread over at least this many different 5 s slots (rules out a single burst)
BAD_SPAN = 20.0           # ……而且第一次到最後一次事件至少相隔這麼多秒（卡頓要"持續"一段時間，不是短短一陣）/ ...first-to-last event at least this many seconds apart (it must be sustained, not a brief blip)
BAD_RATE = 6.0            # ……而且每分鐘至少這麼多次 / ...and at least this many per minute
CLEAN_RATE = 1.5          # 對照狀態每分鐘最多這麼多次才算乾淨 / the baseline state may have at most this many per minute to count as clean
ATTRIB_WINDOW = 300.0     # 卡頓必須出現在最後一個頻道加入後這麼多秒內，才怪它 / stutter must appear within this many seconds of the last join to blame it
REMOVE_COOLDOWN = 90.0    # 停掉一個之後，至少隔這麼久才會再判斷 / after a removal, wait at least this long before judging again
HOLD_SECONDS = 600.0      # 停掉之後，這麼久之內不再派新的頻道進來 / after a removal, assign no new channels for this long
HISTORY = 900.0           # 保留多久的歷史當對照 / how much history to keep as a reference
GRACE = 30.0              # 一個頻道暫時沒在出聲（換歌載入、短暫暫停）這麼久以內，仍算"占用中"，不當成離開再加入 / a channel silent this long (song change, short pause) still counts as "occupied", not as leave + re-join

# 只用來在公告裡說明原因的門檻 / thresholds used only to explain the cause in the announcement
CPU_HIGH = 88.0           # 系統 CPU 使用率（%）/ system CPU usage (%)
LOOP_LAG_HIGH = 0.12      # 事件迴圈延遲（秒）/ event-loop lag (s)
LATENCY_HIGH = 0.30       # 語音連線延遲（秒）/ voice connection latency (s)


# ============================================================
# 探針 / The probe
# ============================================================
class StreamProbe:
    """一首歌的送包時間紀錄

    Packet-timing record for one song. ``record`` is called on every 20 ms read, so it must stay tiny.
    ``count`` = stutter events so far; ``starved`` = how many of those were because ffmpeg was slow.
    """
    __slots__ = ("born", "last", "prev_dt", "count", "starved")

    def __init__(self) -> None:
        self.born = time.perf_counter()
        self.last = 0.0
        self.prev_dt = 0.0
        self.count = 0            # 累計卡頓事件數 / total stutter events
        self.starved = 0          # 其中"來源／編碼跟不上"的次數 / of which "source/encoder too slow"

    def record(self, t0: float, dt: float) -> None:
        """記錄一次讀取：t0 = 開始時間，dt = 這次讀取花的秒數

        Record one read: ``t0`` = start time, ``dt`` = seconds the read took.
        """
        last, prev_dt = self.last, self.prev_dt
        self.last, self.prev_dt = t0, dt
        if not last or t0 - self.born < WARMUP:
            return
        gap = t0 - last
        if LATE_GAP <= gap <= RESUME_GAP:
            self.count += 1
            if prev_dt >= STARVE_READ:
                self.starved += 1


class ProbedSource(discord.AudioSource):
    """把原本的音訊來源包起來，只多量測時間，內容原封不動

    Wraps the original audio source and only adds timing; the audio data passes through untouched.
    """

    def __init__(self, inner: discord.AudioSource, probe: StreamProbe) -> None:
        self._inner, self.probe = inner, probe

    def read(self) -> bytes:
        """讀一個封包並量測花了多久 / Read one packet and measure how long it took."""
        t0 = time.perf_counter()
        data = self._inner.read()
        self.probe.record(t0, time.perf_counter() - t0)
        return data

    def is_opus(self) -> bool:
        return self._inner.is_opus()

    def cleanup(self) -> None:
        self._inner.cleanup()


def probe_source(source, probe: StreamProbe):
    """只有真的是 discord 音訊來源才包（測試用的假來源原樣放行）

    Wrap only real discord audio sources (fake sources used in tests pass through unchanged).
    """
    return ProbedSource(source, probe) if isinstance(source, discord.AudioSource) else source


# ============================================================
# 系統 CPU 使用率 / System CPU usage
# ============================================================
class CpuSampler:
    """系統整體 CPU 使用率（%）；不支援的平台回傳 None，只在偵測器醒來時讀一次

    Whole-system CPU usage (%); returns None on unsupported platforms. Read once per monitor wake-up.
    Windows uses ``GetSystemTimes``; Linux reads ``/proc/stat``.
    """

    def __init__(self) -> None:
        self._prev: tuple[int, int] | None = None

    @staticmethod
    def _read() -> tuple[int, int] | None:      # (忙碌時間, 總時間) / (busy time, total time)
        try:
            if sys.platform == "win32":
                class FT(ctypes.Structure):
                    _fields_ = [("lo", ctypes.c_ulong), ("hi", ctypes.c_ulong)]
                idle, kern, user = FT(), FT(), FT()
                if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user)):
                    return None
                v = lambda f: (f.hi << 32) | f.lo  # noqa: E731
                total = v(kern) + v(user)           # kernel 時間已包含 idle / kernel time already includes idle time
                return total - v(idle), total
            with open("/proc/stat", encoding="ascii") as fh:
                parts = [int(x) for x in fh.readline().split()[1:]]
            idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
            total = sum(parts[:8])
            return total - idle, total
        except (OSError, ValueError, IndexError, AttributeError):
            return None

    def percent(self) -> float | None:
        """從上次到現在的 CPU 使用率；第一次呼叫沒有對照，回傳 None

        CPU usage since the previous call; the very first call has nothing to compare against, so it returns None.
        """
        cur = self._read()
        prev, self._prev = self._prev, cur
        if not cur or not prev or cur[1] <= prev[1]:
            return None
        return max(0.0, min(100.0, 100.0 * (cur[0] - prev[0]) / (cur[1] - prev[1])))


# ============================================================
# 紀錄簿：每個狀態各發生了幾次卡頓 / Ledger: how many stutters happened in each state
# ============================================================
@dataclass
class _Tick:
    """一個 5 秒區間的紀錄 / The record of one 5 s slot."""
    t: float
    k: int            # 這個區間有幾條串流同時在播 / streams playing at the same time in this slot
    dt: float         # 區間長度（秒）/ slot length (s)
    events: int       # 這個區間內全部串流的卡頓事件數 / stutter events over all streams in this slot
    seg: int          # 第幾段（串流數每改變一次就換一段）/ segment number (a new segment starts whenever the stream count changes)
    settled: bool     # 已度過 SETTLE（剛改變的前幾秒不計）/ past SETTLE (the first seconds after a change are ignored)


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
        dt = min(CHECK_INTERVAL * 3, now - self._last_t) if self._last_t is not None else CHECK_INTERVAL
        self._last_t = now
        if k != self.k:
            self.seg_by_add = self.k is None or k > self.k
            self.k, self.seg, self.seg_start = k, self.seg + 1, now
        self.ticks.append(_Tick(now, k, dt, events, self.seg, now - self.seg_start >= SETTLE))
        while self.ticks and now - self.ticks[0].t > HISTORY:
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
        cur = [t for t in self.ticks if t.seg == self.seg and t.settled and now - t.t <= RECENT]
        secs = sum(t.dt for t in cur)
        events = sum(t.events for t in cur)
        hit = [t.t for t in cur if t.events]
        spread = len(hit)
        span = (hit[-1] - hit[0]) if hit else 0.0
        base = [t for t in self.ticks if t.k == k - 1 and t.seg != self.seg and t.settled]
        b_secs, b_events = sum(t.dt for t in base), sum(t.events for t in base)
        ev = Evidence(k, self.age(now), secs, events, spread, b_secs, b_events)
        if secs < OBS_MIN:
            return None, "observing"
        if events < BAD_EVENTS or events / secs * 60 < BAD_RATE:
            return None, "quiet"                      # 偶爾卡一下：濾掉 / an occasional hiccup: filtered out
        if spread < BAD_TICKS or span < BAD_SPAN:
            return None, "burst"                      # 一次爆發、或卡頓沒有持續一段時間：濾掉 / a single burst, or not sustained long enough: filtered out
        if self.age(now) > ATTRIB_WINDOW:
            return None, "late-onset"                 # 不是剛加入的時候才卡：不怪它 / it didn't start right after the join: don't blame the newcomer
        if b_secs < BASE_MIN:
            return None, "no-baseline"                # 沒有"少一條"的乾淨對照：無法確定 / no clean "one fewer" reference: can't be sure
        if b_events / b_secs * 60 > CLEAN_RATE:
            return None, "baseline-dirty"             # 加入前就在卡：不是新加入的造成的 / it was already stuttering before the join: not the newcomer's fault
        return ev, "confirmed"


# ============================================================
# 偵測器 / The monitor
# ============================================================
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


class HealthMonitor:
    """背景偵測器：每 5 秒取一次樣，餵給 Ledger，必要時叫 Hub 停掉最新的頻道

    Background monitor: samples every 5 s, feeds the Ledger and, when warranted, asks the Hub to stop the
    newest channel. ``step`` is pure logic (easy to test); ``run`` is the real-time loop.
    """

    def __init__(self, hub: "Hub") -> None:
        self.hub = hub
        self.cpu = CpuSampler()
        self.ledger = Ledger()
        self._last_removal = -1e9
        self._seen: dict[StreamProbe, tuple[int, int]] = {}
        self._active: dict[object, tuple[float, float]] = {}      # key -> (開始占用, 最後一次看到在播) / key -> (occupied since, last seen playing)
        self._lags: deque[tuple[float, float]] = deque(maxlen=int(RECENT / CHECK_INTERVAL) + 2)
        self._cpus: deque[float] = deque(maxlen=int(RECENT / CHECK_INTERVAL) + 2)
        self._kinds: deque[tuple[int, int]] = deque(maxlen=int(RECENT / CHECK_INTERVAL) + 2)   # (late, starved) 每個區間 / (late, starved) per slot
        self._logged: dict[str, float] = {}

    def samples(self) -> list[Sample]:
        """蒐集所有"正在出聲"的串流 / Collect every stream that is currently producing sound."""
        out = []
        for w in self.hub.workers:
            for g in w.guilds:
                vc, st = g.voice_client, w.state(g.id)
                probe = getattr(st, "probe", None)
                if vc is None or probe is None or not vc.is_playing():
                    continue
                since = st.joined_at or probe.born
                out.append(Sample(f"{w.label}", vc.channel.name, since, probe, getattr(vc, "latency", None), w, g, (id(w), g.id)))
        return out

    def _reasons(self, samples: list[Sample]) -> list[str]:
        """推測可能的原因，寫進公告（只是說明，不影響是否停掉）

        Guess the likely causes for the announcement (purely informative; doesn't affect whether we stop).
        """
        reasons: list[str] = []
        cpu = max(self._cpus, default=0.0)
        lag = max((v for _, v in self._lags), default=0.0)
        late = sum(a for a, _ in self._kinds)
        starved = sum(b for _, b in self._kinds)
        if cpu >= CPU_HIGH:
            reasons.append(f"電腦 CPU 使用率偏高（約 {cpu:.0f}%）")
        if lag >= LOOP_LAG_HIGH:
            reasons.append(f"機器人的處理被拖慢（最長延遲約 {lag * 1000:.0f} 毫秒）")
        if starved and starved * 2 >= starved + late:
            reasons.append("音訊編碼／讀取跟不上（CPU 或硬碟忙碌，或來源網路太慢）")
        lat = max((s.latency or 0.0 for s in samples), default=0.0)
        if lat >= LATENCY_HIGH:
            reasons.append(f"連到 Discord 的網路延遲偏高（約 {lat * 1000:.0f} 毫秒）")
        return reasons or ["送出音訊封包的時間不穩（可能是上傳網路不穩，或電腦同時在忙別的事）"]

    def step(self, now: float, samples: list[Sample], cpu: float | None, lag: float) -> Removal | None:
        """處理一個 5 秒區間的資料；只有"全部條件成立"才回傳要停掉的串流

        Process the data of one 5 s slot; returns the stream to stop only when ALL conditions hold.
        """
        late = starved = 0
        seen_now: dict[StreamProbe, tuple[int, int]] = {}
        for s in samples:
            c0, s0 = self._seen.get(s.probe, (s.probe.count, s.probe.starved))   # 第一次看到：從現在開始算 / first sight: count from now on
            late += s.probe.count - c0
            starved += s.probe.starved - s0
            seen_now[s.probe] = (s.probe.count, s.probe.starved)
        self._seen = seen_now
        self._kinds.append((late - starved, starved))
        self._lags.append((now, lag))
        if cpu is not None:
            self._cpus.append(cpu)

        # 哪些頻道"正在占用"、各自從什麼時候開始：歌曲切換（載入新歌的幾秒）不算離開，所以給一段寬限
        # Which channels are "occupied" and since when: a song change (a few seconds of loading) isn't a
        # leave, so a grace period is applied.
        for s in samples:
            first, last = self._active.get(s.key, (now, now))
            self._active[s.key] = (first if now - last <= GRACE else now, now)
        self._active = {key: v for key, v in self._active.items() if now - v[1] <= GRACE}
        k = len(self._active)
        self.ledger.add(now, k, late)
        if k < 2 or now - self._last_removal < REMOVE_COOLDOWN:
            return None
        ev, why = self.ledger.judge(now)
        if ev is None:
            if why in ("no-baseline", "baseline-dirty", "late-onset") and now - self._logged.get(why, -1e9) > 300:
                self._logged[why] = now
                log.info("播放偵測：持續卡頓，但無法確定是新加入的頻道造成的（%s），不動作", why)
            return None
        # 最後"開始占用"的那個（同一個區間一起開始的，再比進入語音頻道的先後）
        # The one that started being occupied last (ties within one slot are broken by who entered the voice channel later).
        newest = max(samples, key=lambda s: (self._active[s.key][0], s.since))
        self._last_removal = now
        return Removal(newest, k - 1, self._reasons(samples), ev)

    def check(self, now: float | None = None, lag: float = 0.0) -> Removal | None:
        """用真實的樣本與 CPU 讀數跑一次 step / Run ``step`` once with real samples and a real CPU reading."""
        return self.step(time.monotonic() if now is None else now, self.samples(), self.cpu.percent(), lag)

    async def run(self) -> None:
        """永遠執行的迴圈：睡 5 秒 → 量事件迴圈延遲 → 檢查 → 必要時停掉一條串流

        The forever loop: sleep 5 s -> measure event-loop lag -> check -> stop a stream if needed.
        """
        loop = asyncio.get_running_loop()
        while True:
            t = loop.time()
            await asyncio.sleep(CHECK_INTERVAL)
            lag = max(0.0, loop.time() - t - CHECK_INTERVAL)   # 睡超過的時間 = 事件迴圈被拖慢多少 / oversleep = how much the event loop was delayed
            try:
                removal = self.check(lag=lag)
                if removal:
                    await self.hub.remove_stream(removal)
            except Exception:  # noqa: BLE001 - 偵測器自己壞掉不能影響播放 / a bug in the monitor must never affect playback
                log.exception("播放偵測發生錯誤（已忽略）")
