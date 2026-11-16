"""加歌：解析、放進待播、補縮圖標題、進語音頻道

Adding songs: resolve, queue, fill thumbnails and titles, join voice
"""
from __future__ import annotations

import asyncio
import itertools
from typing import TYPE_CHECKING

import discord

from .. import params
from ..sources import Track, enrich_track, resolve_tracks

if TYPE_CHECKING:
    pass


class EnqueueMixin:
    async def enrich_many(self, guild_id: int, tracks: list[Track]) -> None:
        """在背景補齊多首曲目的縮圖等資訊（同時最多 3 個，免得被站方限流）

        Fill in thumbnails etc. for many tracks in the background (at most 3 at a time to avoid rate limits).
        """
        if self._enrich_sem is None:
            self._enrich_sem = asyncio.Semaphore(params.ENRICH_PARALLEL)

        async def one(t: Track) -> None:
            async with self._enrich_sem:
                await asyncio.to_thread(enrich_track, t)
            self.notify(guild_id)

        await asyncio.gather(*(one(t) for t in tracks))

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
        return await self._place(guild, tracks, requester_avatar, voice_channel, when)

    async def enqueue_tracks(
        self, guild: discord.Guild, tracks: list[Track], voice_channel: discord.abc.Connectable | None = None, when: str = "end",
    ) -> tuple[list[Track], str | None]:
        """加入已經做好的曲目（我的歌單用，不用再解析連結），when 同 enqueue

        Add ready-made tracks (used by the library; no link needs resolving). ``when`` as in enqueue.
        """
        try:
            return await self._place(guild, tracks, tracks[0].requester_avatar if tracks else "", voice_channel, when)
        finally:
            self.release(guild.id)

    @staticmethod
    def tracks_from_songs(songs: list[dict], requester: str, avatar: str = "") -> list[Track]:
        """把歌單裡存的歌變回曲目；已經有縮圖的不用再補資料

        Turn stored songs back into tracks; those that already have a thumbnail need no enrichment.
        """
        return [Track(url=s["url"], title=s.get("title") or s["url"], requester=requester, thumbnail=s.get("thumbnail") or "",
                      duration=s.get("duration"), uploader=s.get("uploader") or "", requester_avatar=avatar,
                      search=s.get("search") or "", enriched=bool(s.get("thumbnail"))) for s in songs]

    async def _place(
        self, guild: discord.Guild, tracks: list[Track], requester_avatar: str,
        voice_channel: discord.abc.Connectable | None, when: str,
    ) -> tuple[list[Track], str | None]:
        """曲目放進待播清單、補資料、進語音頻道、開始播（enqueue 和 enqueue_tracks 共用）

        Put tracks into the queue, enrich, join voice and start playing (shared by enqueue and enqueue_tracks).
        """
        st = self.state(guild.id)
        room = params.MAX_QUEUE - len(st.queue)
        if room <= 0:
            return [], f"待播清單已經滿了（上限 {params.MAX_QUEUE} 首）"
        note = f"清單只剩 {room} 個位置，只加入前 {room} 首（上限 {params.MAX_QUEUE} 首）" if len(tracks) > room else None
        tracks = tracks[:room]
        for t in tracks:      # 每次都明確指定（包含空字串），避免沿用快取裡上一位點歌者的頭像 / always set it explicitly (even ""), so a cached result doesn't keep the previous requester's avatar
            t.requester_avatar = requester_avatar
        if when == "end":
            st.queue.extend(tracks)
        else:
            st.queue.extendleft(reversed(tracks))   # 保持多首的原順序，整批插到最前面 / keep the original order of multiple tracks while inserting them at the front
        self.notify(guild.id)
        if len(tracks) == 1:
            if not tracks[0].search and (not tracks[0].thumbnail or not tracks[0].title):
                await asyncio.to_thread(enrich_track, tracks[0])
        else:
            # 只先補前 50 首，其餘等輪到前面時由 _enrich_ahead 補，不然 5000 首會打 5000 次站方
            # Only the first 50 now; the rest are filled by _enrich_ahead as they get close, or 5000 songs would hit the site 5000 times.
            pending = [t for t in tracks if not t.thumbnail and not t.search][: params.ENRICH_FIRST]
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
        return tracks, note

    def _enrich_ahead(self, guild_id: int) -> None:
        """開始播一首時，順便補後面 10 首的縮圖和標題（每首只試一次）
        When a song starts, also fill in the next 10 queued songs (each is tried only once)."""
        nxt = [t for t in itertools.islice(self.state(guild_id).queue, params.ENRICH_AHEAD) if not t.thumbnail and not t.enriched and not t.search]
        if nxt:
            asyncio.create_task(self.enrich_many(guild_id, nxt))
