"""音訊管線的單元測試（不需要 Discord、不連網）：Opus 來源直通、重編的音質參數、遇到不能直通的封包改成重編
Unit tests of the audio pipeline (no Discord, no network): direct Opus, the quality settings for re-encoding, falling back when a packet can't go direct

用 tests/run_all.py 執行 / run it with tests/run_all.py
"""
import os
import sys
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 專案根目錄 / project root
sys.path.insert(0, ROOT)
import discord
from musicbot import params
from musicbot.player import audio
from musicbot.sources.tracks import Stream

res = []
def check(n, ok, d=""): res.append(bool(ok)); print(("PASS" if ok else "FAIL"), n, str(d)[:190], flush=True)

def stream(codec, abr=139): return Stream("https://x/a", {"Referer": "r"}, "t", 200, f"{codec} {abr}kbps", "", codec=codec, abr=abr)

# ============ 預設值 ============
check("D1 預設：Opus 來源直通、重編時預期掉包 0%（音質優先）", params.OPUS_DIRECT == 1 and params.OPUS_PACKET_LOSS == 0, (params.OPUS_DIRECT, params.OPUS_PACKET_LOSS))

# ============ 哪些來源直通 ============
check("C1 Opus 來源直通，AAC 和 FLAC 要重編", audio.is_direct_candidate(stream("opus")) and not audio.is_direct_candidate(stream("mp4a.40.2")) and not audio.is_direct_candidate(stream("flac")))
with mock.patch.object(params, "OPUS_DIRECT", 0):
    check("C2 OPUS_DIRECT=0 時一律重編", not audio.is_direct_candidate(stream("opus")))

# ============ 封包檢查（第一個位元組 TOC）============
def toc(config, frames=0): return bytes([(config << 3) | frames, 0, 0])
check("P1 CELT 20 毫秒單框可以送（YouTube 就是這種）", audio.is_20ms_packet(toc(31)) and audio.is_20ms_packet(toc(19)))
check("P2 10 毫秒、2.5 毫秒的不行", not audio.is_20ms_packet(toc(30)) and not audio.is_20ms_packet(toc(28)))
check("P3 一包兩個框以上的不行", not audio.is_20ms_packet(toc(31, 1)) and not audio.is_20ms_packet(toc(31, 3)))
check("P4 SILK／混合模式的 20 毫秒可以，40／60 毫秒不行", audio.is_20ms_packet(toc(1)) and audio.is_20ms_packet(toc(13)) and not audio.is_20ms_packet(toc(2)) and not audio.is_20ms_packet(toc(3)))
check("P5 空封包不算", not audio.is_20ms_packet(b""))
check("P6 認得檔頭封包", audio.is_header_packet(b"OpusHead\x01\x02") and audio.is_header_packet(b"OpusTags....") and not audio.is_header_packet(toc(31)))

# ============ 重編的參數 ============
opts = audio.encode_options()
check("E1 重編參數：預期掉包 0、不用 FEC、VBR、最高壓縮等級", all(k in opts for k in ("-packet_loss 0", "-fec false", "-vbr on", "-compression_level 10", "-vn")), opts)
with mock.patch.object(params, "OPUS_PACKET_LOSS", 10):
    check("E2 OPUS_PACKET_LOSS 改成 10 時會開 FEC", "-packet_loss 10 -fec true" in audio.encode_options(), audio.encode_options())
before = audio._before_options(stream("opus"), 12.5)
check("E3 跳轉放在來源之前、帶重連和標頭", before.startswith("-ss 12.50 ") and "-reconnect 1" in before and "Referer: r" in before, before[:60])
check("E4 從頭播不帶 -ss", "-ss" not in audio._before_options(stream("opus"), 0.0))
audio.has_resampler.cache_clear()
with mock.patch.object(audio.subprocess, "run", lambda *a, **k: mock.Mock(stdout=b"configuration: --enable-libopus --enable-libsoxr")):
    with_soxr = audio.encode_options("ffmpeg-a")
with mock.patch.object(audio.subprocess, "run", lambda *a, **k: mock.Mock(stdout=b"configuration: --enable-libopus")):
    without = audio.encode_options("ffmpeg-b")
check("E5 ffmpeg 有 soxr 才用它轉取樣率，沒有就用預設的", "aresample=resampler=soxr" in with_soxr and "aresample" not in without, (with_soxr[-45:], without[-30:]))
def boom(*a, **k): raise OSError("no ffmpeg")
with mock.patch.object(audio.subprocess, "run", boom):
    check("E6 問不到 ffmpeg 也不會壞", "aresample" not in audio.encode_options("ffmpeg-c"))
audio.has_resampler.cache_clear()


# ============ 直通與改成重編 ============
class Fake(discord.AudioSource):
    def __init__(self, packets): self.packets, self.cleaned = list(packets), False
    def read(self): return self.packets.pop(0) if self.packets else b""
    def is_opus(self): return True
    def cleanup(self): self.cleaned = True

good = [toc(31) + bytes([i]) for i in range(5)]
src = audio.DirectOpus(Fake([b"OpusHead..", b"OpusTags.."] + good), lambda pos: Fake([]), 0.0)
out = [src.read() for _ in range(6)]
check("F1 直通：跳過檔頭，聲音封包原封不動", out == good + [b""] and src.direct, out[:2])

made, called = [], []
inner = Fake(good[:3] + [toc(30)] + good[3:])            # 第四包是 10 毫秒 / the fourth packet is 10 ms
enc = Fake([b"E1", b"E2"])
src = audio.DirectOpus(inner, lambda pos: (made.append(pos), enc)[1], 30.0, lambda: called.append(1))
out = [src.read() for _ in range(5)]
check("F2 遇到不能直通的封包：改成重編，接著讀重編的輸出", out == good[:3] + [b"E1", b"E2"] and not src.direct, out)
check("F3 重編從目前位置接（30 秒 + 3 包 × 20 毫秒）", made == [30.0 + 3 * 0.02], made)
check("F4 原本的來源有關掉，而且有通知", inner.cleaned and called == [1])
src.cleanup()
check("F5 結束時關掉目前的來源", enc.cleaned)

with mock.patch.object(audio, "copied", lambda s, o, f: Fake(good)), mock.patch.object(audio, "encoded", lambda s, b, o, f: Fake([b"E"])):
    a, direct_a = audio.build(stream("opus"), 256, 0.0, "ffmpeg")
    b, direct_b = audio.build(stream("mp4a.40.2", 192), 256, 0.0, "ffmpeg")
    check("B1 build：Opus 走直通，AAC 走重編", direct_a and isinstance(a, audio.DirectOpus) and not direct_b and b.read() == b"E")

print(f"{sum(res)}/{len(res)} 通過", flush=True)
sys.exit(0 if all(res) else 1)
