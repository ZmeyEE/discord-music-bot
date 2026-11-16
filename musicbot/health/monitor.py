"""背景監看：每 5 秒讀一次計數，決定要不要停掉最後加入的頻道

Background monitor: reads the counters every 5 s and decides whether to stop the newest channel
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import TYPE_CHECKING

from .. import params
from .ledger import Ledger, Removal, Sample
from .probe import CpuSampler, StreamProbe

if TYPE_CHECKING:
    from ..hub import Hub
log = logging.getLogger("musicbot")

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
        self._lags: deque[tuple[float, float]] = deque(maxlen=int(params.RECENT / params.CHECK_INTERVAL) + 2)
        self._cpus: deque[float] = deque(maxlen=int(params.RECENT / params.CHECK_INTERVAL) + 2)
        self._kinds: deque[tuple[int, int]] = deque(maxlen=int(params.RECENT / params.CHECK_INTERVAL) + 2)   # (late, starved) 每個區間 / (late, starved) per slot
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
        if cpu >= params.CPU_HIGH:
            reasons.append(f"電腦 CPU 使用率偏高（約 {cpu:.0f}%）")
        if lag >= params.LOOP_LAG_HIGH:
            reasons.append(f"機器人的處理被拖慢（最長延遲約 {lag * 1000:.0f} 毫秒）")
        if starved and starved * 2 >= starved + late:
            reasons.append("音訊編碼／讀取跟不上（CPU 或硬碟忙碌，或來源網路太慢）")
        lat = max((s.latency or 0.0 for s in samples), default=0.0)
        if lat >= params.LATENCY_HIGH:
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
            self._active[s.key] = (first if now - last <= params.GRACE else now, now)
        self._active = {key: v for key, v in self._active.items() if now - v[1] <= params.GRACE}
        k = len(self._active)
        self.ledger.add(now, k, late)
        if k < 2 or now - self._last_removal < params.REMOVE_COOLDOWN:
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
            await asyncio.sleep(params.CHECK_INTERVAL)
            lag = max(0.0, loop.time() - t - params.CHECK_INTERVAL)   # 睡超過的時間 = 事件迴圈被拖慢多少 / oversleep = how much the event loop was delayed
            try:
                removal = self.check(lag=lag)
                if removal:
                    await self.hub.remove_stream(removal)
            except Exception:  # noqa: BLE001 - 偵測器自己壞掉不能影響播放 / a bug in the monitor must never affect playback
                log.exception("播放偵測發生錯誤（已忽略）")
