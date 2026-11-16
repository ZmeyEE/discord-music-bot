"""音訊管線：把一條串流變成送進 Discord 的 Opus 封包，音質損失降到最低

兩條路：
  1. 直通：來源本身就是 Opus（YouTube 的最佳音軌）→ 原封不動送出去，不重新編碼，零損失
  2. 重編：其他來源（Bilibili 的 AAC／FLAC）→ 用 libopus 編一次，參數調成音質優先

為什麼要自己給編碼參數：discord.py 內建寫死"預期掉包 15%"（-packet_loss 15 -fec true），這會犧牲音質換抗掉包
實測同一首歌編碼後和原音的波形相似度：256k 時 16.2 dB → 23.9 dB，510k 時 10.8 dB → 26.0 dB（改成 0% 之後）

Audio pipeline: turn a stream into the Opus packets sent to Discord with as little quality loss as possible.

Two paths:
  1. Direct: the source is Opus already (YouTube's best track) -> sent untouched, no re-encoding, zero loss.
  2. Re-encode: anything else (Bilibili's AAC / FLAC) -> one libopus pass with quality-first settings.

Why we pass our own encoder settings: discord.py hard-codes "expect 15% packet loss" (-packet_loss 15 -fec true), which
trades quality for loss resilience. Measured waveform similarity to the source for one song: 16.2 dB -> 23.9 dB at 256k and
10.8 dB -> 26.0 dB at 510k once it is set to 0%.
"""
from __future__ import annotations

import functools
import shlex
import subprocess
from typing import Callable

import discord

from .. import params
from ..sources import Stream
from .state import ffmpeg_stderr

FRAME_SECONDS = 0.02   # Discord 的語音一包固定 20 毫秒 / a Discord voice packet is always 20 ms


def is_direct_candidate(stream: Stream) -> bool:
    """這條串流可以直通嗎：來源是 Opus 而且直通有開 / May this stream go direct: the source is Opus and direct mode is on."""
    return bool(params.OPUS_DIRECT) and stream.codec.lower().startswith("opus")


def is_20ms_packet(packet: bytes) -> bool:
    """這個 Opus 封包是不是"一包一個 20 毫秒的框"（Discord 只能這樣送），看第一個位元組（TOC）就知道

    Is this Opus packet "one 20 ms frame per packet" (the only shape Discord can carry)? The first byte (TOC) tells:
    bits 3-7 = configuration (which gives the frame length), bits 0-1 = how many frames are in the packet.
    """
    if not packet:
        return False
    config, frames = packet[0] >> 3, packet[0] & 0x03
    if config < 12:                      # SILK：10、20、40、60 毫秒輪流 / SILK: 10, 20, 40, 60 ms in turn
        twenty = config % 4 == 1
    elif config < 16:                    # 混合：10、20 毫秒輪流 / hybrid: 10, 20 ms in turn
        twenty = config % 2 == 1
    else:                                # CELT：2.5、5、10、20 毫秒輪流 / CELT: 2.5, 5, 10, 20 ms in turn
        twenty = config % 4 == 3
    return twenty and frames == 0        # frames == 0 表示一包只有一個框 / frames == 0 means a single frame in the packet


def is_header_packet(packet: bytes) -> bool:
    """Ogg/Opus 開頭的兩個說明封包（OpusHead、OpusTags），不是聲音 / The two descriptive packets at the start of Ogg/Opus (OpusHead, OpusTags); not audio."""
    return packet[:8] in (b"OpusHead", b"OpusTags")


def _before_options(stream: Stream, offset: float) -> str:
    """ffmpeg 讀來源之前的參數：跳轉、斷線重連、站方要求的標頭 / Options before the input: seek, reconnect, the headers the site requires."""
    header_blob = "".join(f"{k}: {v}\r\n" for k, v in stream.headers.items())
    seek = f"-ss {offset:.2f} " if offset > 0 else ""   # -ss 放在 -i 之前 = 快速跳轉 / -ss before -i = fast seek
    return (
        f"{seek}-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "   # 網路斷線時自動重連 / auto-reconnect on network hiccups
        f"-headers {shlex.quote(header_blob)}"
    )


@functools.lru_cache(maxsize=4)
def has_resampler(ffmpeg: str, name: str) -> bool:
    """這個 ffmpeg 有沒有內建指定的取樣率轉換器（問一次就記住；啟動時先問好，播放時不用等）

    Does this ffmpeg build include the named resampler? Asked once and remembered (asked at start-up, so playback never waits).
    """
    if not name:
        return False
    try:
        out = subprocess.run([ffmpeg, "-hide_banner", "-buildconf"], capture_output=True, timeout=10,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return f"--enable-lib{name}".encode() in out


def encode_options(ffmpeg: str = "") -> str:
    """重編時給 libopus 的參數（寫在 discord.py 內建參數後面，後寫的會蓋掉前面的）

    The libopus settings for re-encoding. They come after discord.py's built-in arguments, and the later ones win.
    """
    resample = f" -af aresample=resampler={params.RESAMPLER}:precision=28" if ffmpeg and has_resampler(ffmpeg, params.RESAMPLER) else ""
    return (
        f"-vn -packet_loss {params.OPUS_PACKET_LOSS} -fec {'true' if params.OPUS_PACKET_LOSS else 'false'} "
        f"-vbr on -compression_level 10 -application audio{resample}"
    )


def encoded(stream: Stream, bitrate: int, offset: float, ffmpeg: str) -> discord.AudioSource:
    """重編成 Opus（bitrate kbps）/ Re-encode to Opus at ``bitrate`` kbps."""
    return discord.FFmpegOpusAudio(
        stream.url, bitrate=bitrate, executable=ffmpeg, before_options=_before_options(stream, offset),
        options=encode_options(ffmpeg), stderr=ffmpeg_stderr(),
    )


def copied(stream: Stream, offset: float, ffmpeg: str) -> discord.AudioSource:
    """直通：-c:a copy，封包原封不動 / Direct: -c:a copy, the packets are untouched."""
    return discord.FFmpegOpusAudio(
        stream.url, codec="copy", executable=ffmpeg, before_options=_before_options(stream, offset),
        options="-vn", stderr=ffmpeg_stderr(),
    )


class DirectOpus(discord.AudioSource):
    """直通來源，邊送邊檢查每一包；遇到不是 20 毫秒單框的封包（Discord 送不了），就從目前位置改成重編，使用者只會聽到一小段空白

    The direct source, checking every packet as it goes. On a packet that is not a single 20 ms frame (Discord can't carry
    it) it switches to re-encoding from the current position; listeners hear only a short gap.
    """

    def __init__(self, direct: discord.AudioSource, fallback: Callable[[float], discord.AudioSource], offset: float,
                 on_fallback: Callable[[], None] | None = None) -> None:
        self.inner, self.fallback, self.offset, self.on_fallback = direct, fallback, offset, on_fallback
        self.direct, self.packets = True, 0

    def read(self) -> bytes:
        data = self.inner.read()
        while self.direct and is_header_packet(data):   # 檔頭不是聲音，跳過 / the stream headers are not audio: skip them
            data = self.inner.read()
        if self.direct and data and not is_20ms_packet(data):
            self.inner.cleanup()
            self.direct = False
            self.inner = self.fallback(self.offset + self.packets * FRAME_SECONDS)
            if self.on_fallback:
                self.on_fallback()
            data = self.inner.read()
        self.packets += 1
        return data

    def is_opus(self) -> bool:
        return True

    def cleanup(self) -> None:
        self.inner.cleanup()


def build(stream: Stream, bitrate: int, offset: float, ffmpeg: str,
          on_fallback: Callable[[], None] | None = None) -> tuple[discord.AudioSource, bool]:
    """建立音訊來源，回傳 (來源, 是不是直通) / Build the audio source: ``(source, is it direct)``."""
    if is_direct_candidate(stream):
        return DirectOpus(copied(stream, offset, ffmpeg), lambda pos: encoded(stream, bitrate, pos, ffmpeg), offset, on_fallback), True
    return encoded(stream, bitrate, offset, ffmpeg), False
