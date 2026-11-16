"""同時播放的上限：卡頓偵測停掉頻道後暫時壓住數量，並公告

Simultaneous-stream cap: lowered for a while after the stutter detector stops a channel, with an announcement
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

import discord

from .. import params

if TYPE_CHECKING:
    pass
log = logging.getLogger("musicbot")


class StreamsMixin:
    # 沒有固定上限；卡頓偵測停掉頻道後暫時壓低
    # There is no fixed limit; it is lowered temporarily after the stutter detector removes a channel.
    @property
    def stream_limit(self) -> int:
        """目前允許同時占用的串流數，平常 = 機器人帳號數（分身不設上限）；
        偵測到卡頓、停掉一個頻道後，params.HOLD_SECONDS 內暫時壓在"停掉後剩下的數量"，之後自動恢復

        How many streams may be occupied right now. Normally = the number of bot accounts (clones are
        unlimited). After the stutter detector stops a channel, it is held at "what remains" for
        params.HOLD_SECONDS and then recovers by itself.
        """
        cap = len(self.workers)
        if self._ceiling is not None and time.monotonic() < self._ceiling_until:
            return max(1, min(self._ceiling, cap))
        return cap

    @property
    def stream_notice(self) -> str | None:
        """壓低期間顯示在看板上的公告；期滿自動消失

        The announcement shown on the dashboard while the cap is lowered; disappears by itself when it expires.
        """
        if self.limit_notice and time.monotonic() < self._ceiling_until:
            return self.limit_notice["text"]
        return None

    def streaming_now(self) -> int:
        """目前占用中的串流數（所有伺服器合計）：已在語音頻道，或已被預約

        Streams occupied right now (all servers combined): already in a voice channel or reserved.
        """
        return sum(1 for w in self.workers for g in w.guilds if g.voice_client or w.state(g.id).reserved)

    def at_stream_limit(self) -> bool:
        """是否已達同時播放上限 / Whether the simultaneous-stream limit has been reached."""
        return self.streaming_now() >= self.stream_limit

    async def remove_stream(self, removal) -> None:
        """卡頓偵測確定是"最後加入的頻道"造成的：公告原因，然後只停掉那一個

        The stutter detector is sure that "the newest channel" caused it: announce the reason, then stop
        only that one. The announcement goes to every voice channel's text chat and the dashboard banner.
        """
        s = removal.sample
        ev = removal.evidence
        reason = "；".join(removal.reasons)
        mins = int(params.HOLD_SECONDS // 60)
        text = (f"偵測到音樂卡頓，而且是從「{s.channel}」（{s.label}）加入之後才開始的"
                f"（它加入前的 {ev.base_seconds:.0f} 秒很順，加入後 {ev.recent_seconds:.0f} 秒內卡了 {ev.recent_events} 次）。"
                f"原因：{reason}。為了讓其他頻道維持順暢，已停止「{s.channel}」的播放並讓它離開"
                f"（它的待播清單已清空，想聽請稍後重新點歌）。目前還有 {removal.remaining} 個頻道在播放；"
                f"接下來 {mins} 分鐘內不再派新的頻道進來。如果仍然卡頓，會再次確認後繼續逐個停止。") if ev else \
               f"偵測到音樂卡頓（{reason}），已停止「{s.channel}」的播放。"
        self._ceiling, self._ceiling_until = removal.remaining, time.monotonic() + params.HOLD_SECONDS
        self.limit_notice = {"text": text, "at": time.time()}
        log.warning("播放卡頓：停止最後加入的頻道「%s」（%s），剩 %d 個；原因：%s", s.channel, s.label, removal.remaining, reason)
        targets = [g.voice_client.channel for w in self.workers for g in w.guilds if g.voice_client and g.voice_client.channel]
        if not params.notices_allow(problem=True):   # CHANNEL_NOTICES=off：連這則也不發（看板上方的公告還是會顯示）/ CHANNEL_NOTICES=off: not even this one (the banner on the dashboard still shows)
            return
        await asyncio.wait_for(asyncio.gather(*(self._announce(ch, text) for ch in targets), return_exceptions=True), 8)
        await s.worker.stop(s.guild)
        self._notify_all()
        asyncio.get_running_loop().call_later(params.HOLD_SECONDS + 1, self._notify_all)   # 期滿時讓看板的公告自己消失 / when it expires, let the dashboard banner disappear by itself

    @staticmethod
    async def _announce(channel, text: str) -> None:
        """在語音頻道自帶的文字聊天室發公告；失敗就算了 / Post an announcement in a voice channel's built-in text chat; failures are ignored."""
        try:
            await channel.send(text)         # 語音頻道自帶的文字聊天室 / the voice channel's built-in text chat
        except (discord.HTTPException, AttributeError):
            pass

    def all_busy_message(self, gid: int) -> str:
        """找不到可用的播放器時，回覆使用者的說明文字（依情況不同：被壓低／只有一個機器人／全部忙碌）

        The explanation shown when no player is available. It depends on the situation: cap lowered after a
        stutter / only one bot account / all players busy.
        """
        if self.stream_limit < len(self.workers):
            return (f"剛剛偵測到音樂卡頓、停止了最後加入的頻道，所以 {int(params.HOLD_SECONDS // 60)} 分鐘內暫時不再增加新的頻道"
                    f"（目前同時播放上限 {self.stream_limit} 個）。等其他頻道結束播放，或稍後再試。")
        n = len(self.players(gid))
        if n <= 1:
            return ("目前只有 1 個機器人帳號，而它正在另一個語音頻道播放。Discord 規定一個機器人在同一個伺服器只能待在一個語音頻道；"
                    "要多頻道同時播放，要有第 2 個機器人帳號：到 Developer Portal 建一個，再雙擊 add-clone.bat 貼上它的 Token（見 README「分身」）。")
        return f"這個伺服器的 {n} 個播放器都在使用中。等其中一個閒置，或用 add-clone.bat 再新增一個分身。"
