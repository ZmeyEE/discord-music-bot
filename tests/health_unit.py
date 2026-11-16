"""卡頓偵測的單元測試（不需要 Discord 或 harness，用假時間模擬）
Unit tests for the stutter detector (no Discord or harness needed, uses fake time)

用 tests/run_all.py 或 tests/run_relay.py 執行 / run it with tests/run_all.py or tests/run_relay.py
"""
import os
import sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 專案根目錄 / project root
sys.path.insert(0, ROOT)
import discord
from musicbot import health as H
from musicbot import params
from musicbot.health import StreamProbe, ProbedSource, HealthMonitor, Sample

res = []
def check(n, ok, d=""): res.append(bool(ok)); print(("PASS" if ok else "FAIL"), n, str(d)[:190], flush=True)

# ============ 探針：怎樣算一次卡頓 ============
def feed(gaps, dts=None, warm=True):
    p = StreamProbe(); t = p.born + (params.WARMUP + 0.5 if warm else 0.0)
    dts = dts or [0.001] * len(gaps)
    p.record(t, 0.001)
    for g, dt in zip(gaps, dts):
        t += g; p.record(t, dt)
    return p
check("P1 正常的 20ms 節奏：零事件", feed([0.020] * 500).count == 0)
p = feed([0.020] * 50 + [0.085] + [0.020] * 50)
check("P2 一次 85ms 的延遲：記一次", p.count == 1 and p.starved == 0, p.count)
check("P3 輕微抖動（<60ms）不算", feed([0.020, 0.025, 0.040, 0.020]).count == 0)
check("P4 暫停／跳轉造成的長間隔（3 秒）不算卡頓", feed([0.020] * 5 + [3.0] + [0.020] * 5).count == 0)
p = feed([0.020, 0.020, 0.090, 0.020], dts=[0.001, 0.080, 0.001, 0.001])
check("P5 上一次讀取等 ffmpeg 80ms：歸類為來源／編碼跟不上，且只記一次", p.count == 1 and p.starved == 1, (p.count, p.starved))
check("P6 開播前 3 秒（暖機）不計", feed([0.5, 0.2, 0.3], warm=False).count == 0)

# ============ 包裝來源：內容與行為不變 ============
class Src(discord.AudioSource):
    def __init__(self): self.n = 0; self.cleaned = False
    def read(self): self.n += 1; return b"x" * 3 if self.n <= 3 else b""
    def is_opus(self): return True
    def cleanup(self): self.cleaned = True
inner = Src(); w = ProbedSource(inner, StreamProbe())
check("W1 資料原封不動、結束訊號（空 bytes）照常傳遞", [w.read() for _ in range(4)] == [b"x" * 3] * 3 + [b""])
check("W2 is_opus 與 cleanup 轉給原來源", w.is_opus() is True and (w.cleanup() or inner.cleaned))
check("W3 是合法的 discord.AudioSource（vc.play 接受）", isinstance(w, discord.AudioSource))
check("W4 假來源（非 AudioSource）原樣放行", H.probe_source(object(), StreamProbe()).__class__ is object)
big = Src(); big.read = lambda: b"y" * 3840
wp = ProbedSource(big, StreamProbe()); N = 50000
t0 = time.perf_counter()
for _ in range(N): big.read()
base = time.perf_counter() - t0; t0 = time.perf_counter()
for _ in range(N): wp.read()
per = ((time.perf_counter() - t0) - base) / N * 1e6
check("W5 探針額外成本極小（每次讀取 < 30 微秒）", per < 30, f"{per:.2f} µs/次")

# ============ 情境模擬（假時間，每格 5 秒）============
class Sim:
    def __init__(self, cpu=10.0):
        self.m = HealthMonitor(None); self.m.cpu.percent = lambda: cpu
        self.now = 10000.0; self.streams = {}; self.order = 0; self.removals = []; self.paused = set()
    def add(self, name):
        self.order += 1; self.streams[name] = (StreamProbe(), float(self.order)); self.paused.discard(name)
    def drop(self, name): self.streams.pop(name, None)
    def pause(self, name): self.paused.add(name)
    def resume(self, name): self.paused.discard(name)
    def tick(self, ev=None, lag=0.0, lat=0.04):
        ev = ev or {}; self.now += 5
        samples = []
        for name, (probe, since) in self.streams.items():
            probe.count += ev.get(name, 0)
            if name in self.paused: continue
            samples.append(Sample(name, f"頻道-{name}", since, probe, lat, name, 1, (name, 1)))
        r = self.m.step(self.now, samples, self.m.cpu.percent(), lag)
        if r:
            self.removals.append((self.now, r.sample.label, r))
            self.drop(r.sample.label)            # 和正式程式一樣：被停掉的頻道離開語音頻道
        return r
    def run(self, n, ev=None, **kw):
        for _ in range(n): self.tick(ev, **kw)
    def names(self): return [x[1] for x in self.removals]
ALL = lambda sim, n=1: {k: n for k in sim.streams}

s = Sim(); s.add("A"); s.run(200, {"A": 1})
check("S1 只有 1 個頻道（再怎麼卡）：永遠不停它", not s.removals)

s = Sim(); s.add("A"); s.run(12); s.add("B"); s.run(120)
check("S2 加入後一切順暢：不動作", not s.removals)

s = Sim(); s.add("A"); s.run(12); s.add("B"); t_add = s.now
s.run(40, {"A": 1, "B": 1})
check("S3 加入前很順、加入後持續卡：停掉最後加入的 B（而不是 A）", s.names() == ["B"], s.names())
t_rm, _, rm = s.removals[0]
check("S3b 要等足夠的觀察時間才動手（≥ 30 秒，不是一卡就停）", t_rm - t_add >= 38, f"{t_rm - t_add:.0f}s")
check("S3c 證據帶有『加入前』的乾淨觀察秒數與『加入後』的卡頓次數", rm.evidence.base_seconds >= 40 and rm.evidence.recent_events >= 4 and rm.remaining == 1, vars(rm.evidence))
check("S3d 有給原因（不是空白）", rm.reasons and all(rm.reasons))

s = Sim(); s.add("A"); s.run(12); s.add("B"); s.run(130)
for _ in range(40): s.tick({"A": 1} if s.m.ledger.age(s.now) >= 0 else None) if False else None
s2 = Sim(); s2.add("A"); s2.run(12); s2.add("B")
for i in range(120):                                    # 每 6 格（30 秒）才 1 次事件：偶爾卡一下
    s2.tick({"B": 1} if i % 6 == 0 else None)
check("S4 偶爾卡一下（每 30 秒 1 次）：濾掉，不動作", not s2.removals, s2.names())

s = Sim(); s.add("A"); s.run(12); s.add("B"); s.run(3)
s.tick({"A": 4, "B": 4}); s.run(30)
check("S5 一次爆發（同一格 8 次）後恢復順暢：濾掉，不動作", not s.removals, s.names())

s = Sim(); s.add("A"); s.run(12); s.add("B"); s.run(3)
s.run(3, {"A": 1, "B": 1}); s.run(30)
check("S5b 只卡短短一陣（15 秒內 6 次、之後恢復）：持續時間不夠，濾掉", not s.removals, s.names())

s = Sim(); s.add("A"); s.run(12); s.add("B"); s.run(5 * 12 + 6)
s.run(60, {"A": 1, "B": 1})
check("S6 加入後 5 分鐘以上才開始卡：不怪新加入的（多半是別的程式）", not s.removals, s.names())

s = Sim(); s.add("A"); s.run(3); s.add("B"); s.run(40, {"A": 1, "B": 1})
check("S7 沒有足夠的『少一條』乾淨對照（加入前只觀察 15 秒）：無法確定，不動作", not s.removals, s.names())

s = Sim(); s.add("A"); s.run(14, {"A": 1}); s.add("B"); s.run(40, {"A": 1, "B": 1})
check("S8 加入前就已經在卡：不是新加入的造成的，不動作", not s.removals, s.names())

# ---- 緩衝：絕不會因為一次卡頓把頻道全停光 ----
s = Sim()
for n in "ABCDE":
    s.add(n); s.run(14)
s.add("F"); s.run(60, {k: 1 for k in s.streams})
check("S9 5 個頻道各自穩定後，第 6 個加入就卡：只停最後加入的 F", s.names() == ["F"], s.names())
s.run(240, {k: 1 for k in s.streams})
check("S9b 停掉之後如果還是卡（代表原因不在新加入的）：不會繼續停，不會停光", s.names() == ["F"] and len(s.streams) == 5, (s.names(), len(s.streams)))

# ---- 逐個停：每次都要重新有新的頻道加入、並重新確認 ----
s = Sim()
for n in "AB":
    s.add(n); s.run(14)
s.add("C")
for _ in range(40):                                    # C 加入後卡，直到被停掉為止（停掉後問題就消失了）
    if s.tick({k: 1 for k in s.streams}): break
first = list(s.names())
s.run(20)                                              # 恢復順暢
s.add("D"); s.run(8)
for _ in range(60):
    if s.tick({k: 1 for k in s.streams}): break
check("S10 再加入新頻道又卡：重新確認後才再停（先 C、後 D，一次一個）", first == ["C"] and s.names() == ["C", "D"], s.names())
gap = s.removals[1][0] - s.removals[0][0]
check("S10b 兩次停止之間隔著緩衝（≥ 90 秒）", gap >= 90, f"{gap:.0f}s")

# ---- 暫停後恢復算『新加入』；換歌的短暫空檔不算 ----
s = Sim(); s.add("A"); s.add("C"); s.add("B"); s.run(14)
s.pause("C"); s.run(18)                                 # 暫停 90 秒（超過 30 秒寬限）：不占用，期間 A、B 兩條很順
s.resume("C"); s.run(40, {k: 1 for k in s.streams})
check("S11 暫停超過寬限後恢復，算『最後加入』：停的是 C，不是 B", s.names() == ["C"], s.names())
s = Sim(); s.add("A"); s.add("B"); s.run(14); seg0 = s.m.ledger.seg
s.pause("B"); s.run(3); s.resume("B"); s.run(10)
check("S12 換歌／短暫暫停（15 秒 < 寬限）不會被當成離開再加入（紀錄簿不換段）", s.m.ledger.seg == seg0, (seg0, s.m.ledger.seg))

# ---- 原因說明 ----
s = Sim(cpu=96.0); s.add("A"); s.run(14); s.add("B"); s.run(40, {"A": 1, "B": 1}, lag=0.4)
r = s.removals[0][2]
check("S13 原因：CPU 使用率與處理延遲都寫進去", any("CPU" in x and "96" in x for x in r.reasons) and any("拖慢" in x for x in r.reasons), r.reasons)
s = Sim(); s.add("A"); s.run(14); s.add("B"); s.run(40, {"A": 1, "B": 1}, lat=0.5)
check("S14 原因：Discord 網路延遲偏高", any("網路延遲" in x and "500" in x for x in s.removals[0][2].reasons), s.removals[0][2].reasons)

# ---- 系統 CPU 取樣器 ----
cs = H.CpuSampler(); first = cs.percent(); t_end = time.time() + 0.6
while time.time() < t_end: pass
second = cs.percent()
check("C1 第一次取樣沒有基準（None），第二次回傳 0~100 的數字", first is None and second is not None and 0 <= second <= 100, (first, second))
print(f"總結：{sum(res)}/{len(res)} 通過")
