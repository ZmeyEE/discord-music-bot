"""量測：每首歌的送包時間紀錄（探針）、包住音源的 ProbedSource、系統 CPU 取樣

Measuring: the per-song packet-timing probe, the ProbedSource wrapper, and the system CPU sampler
"""
from __future__ import annotations

import ctypes
import sys
import time
from typing import TYPE_CHECKING

import discord

from .. import params

if TYPE_CHECKING:
    pass


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
        if not last or t0 - self.born < params.WARMUP:
            return
        gap = t0 - last
        if params.LATE_GAP <= gap <= params.RESUME_GAP:
            self.count += 1
            if prev_dt >= params.STARVE_READ:
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
