"""網頁送來的操作：加歌、跳過、暫停…

Actions sent by the dashboard: add, skip, pause...
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .. import bilibili, sources
from .models import UserCtx

if TYPE_CHECKING:
    pass


class ActionsMixin:
    async def handle_action(self, gid: int, ctx: UserCtx, pid: str | None, msg: dict) -> str | None:
        """後台送來的操作，回傳要顯示給使用者的提示訊息（或 None）

        Handle an action sent by the dashboard (add, skip, move, ...). Returns a message to show the
        user, or None. Every action passes the permission check (``can_control``) first.
        """
        t = msg.get("type")
        if ctx.pending:
            return "請先在 Discord 輸入 /help，點它給你的專屬連結"

        if t == "add":
            return await self._action_add(gid, ctx, pid, msg)

        if t == "bili_logout":
            if not self.is_owner(ctx):
                return "只有機器人的擁有者可以更換 Bilibili 帳號"
            bilibili.logout()
            sources.clear_search_cache()
            self._notify_all()
            return "已登出 Bilibili 帳號"

        player = self.resolve_player(gid, ctx, pid)

        if t == "quality":
            ok, reason = self.can_control(ctx, gid, None)
            if not ok:
                return reason
            try:
                kbps = int(msg.get("kbps", 0))
            except (TypeError, ValueError):
                return "不支援的音質選項"
            if not self.set_quality(gid, kbps):
                return "不支援的音質選項"
            return f"這個伺服器的音質已切換為 Opus {kbps} kbps，正在播放的歌會從原位置重新開始"

        if player is None:
            return "目前沒有播放器，先在語音頻道加一首歌吧"
        ok, reason = self.can_control(ctx, gid, player)
        if not ok:
            return reason

        w, g = player.worker, player.guild
        if t == "move":
            w.move_track(gid, str(msg.get("id", "")), int(msg.get("index", 0)))
        elif t == "remove":
            w.remove_track(gid, str(msg.get("id", "")))
        elif t == "play_now":
            await w.play_now(g, str(msg.get("id", "")))
        elif t == "loop":
            w.set_loop(gid, str(msg.get("mode", "off")))
        elif t == "skip":
            w.skip(g)
        elif t == "remove_current":
            w.remove_current(g)
        elif t == "seek":
            try:
                w.seek(g, float(msg.get("position", 0)))
            except (TypeError, ValueError):
                return "跳轉位置不正確"
        elif t == "toggle_pause":
            if not w.pause(g):
                w.resume(g)
        elif t == "stop":
            await w.stop(g)
        elif t == "shuffle":
            w.shuffle(gid)
        elif t == "clear":
            w.clear_queue(gid)
        return None

    async def _action_add(self, gid: int, ctx: UserCtx, pid: str | None, msg: dict) -> str | None:
        """(加歌)動作：決定要放進哪個頻道／播放器，再交給 PlayerBot.enqueue

        The "add a song" action: decide which channel / player it goes to, then hand it to PlayerBot.enqueue.
        """
        q = str(msg.get("query", "")).strip()[:500]
        if not q:
            return "請輸入網址或關鍵字"
        when = msg.get("when") if msg.get("when") in ("end", "next", "now") else "end"

        voice_channel = None
        if self.free_control or ctx.is_host:
            # 開放／驗證模式／本地：不用管使用者人在哪，由"他在看板上選的頻道或播放器"決定放去哪
            # open / verify mode / local: it doesn't matter where the user is; the channel or player picked on the dashboard decides.
            cid = str(msg.get("channel") or "")
            if cid.isdigit():
                target = self._target_channel(gid, int(cid))
                if isinstance(target, str):
                    return target
                worker, guild, voice_channel = target
            else:
                player = self.resolve_player(gid, ctx, pid)
                if player:
                    worker, guild = player.worker, player.guild
                else:
                    vch = self.voice_channel_of(gid, ctx.user_id)      # 帶了憑證、人在語音頻道的話，就去他那個頻道 / has a token and sits in a voice channel: go to that channel
                    if vch is not None:
                        target = self._target_channel(gid, vch.id)
                        if isinstance(target, str):
                            return target
                        worker, guild, voice_channel = target
                    elif ctx.is_host and (g := self.primary.get_guild(gid)) and self.primary.state(gid).last_voice_id:
                        worker, guild = self.primary, g              # 本地：回到上次的頻道 / local: go back to the last channel
                    else:
                        return "請先選一個語音頻道（上方「+ 加到頻道」），機器人才知道要去哪裡放歌"
        else:
            # 語音模式：只有人在語音頻道裡才能加歌，並且放進他所在頻道的播放器
            # voice mode: only people inside a voice channel may add songs, and they go to that channel's player.
            worker, guild, vch = self.pick_for_user(gid, ctx.user_id, create=True)
            if vch is None:
                return "請先加入語音頻道，機器人才知道要去哪裡放歌（現在是唯讀）"
            if worker is None:
                return self.all_busy_message(gid)
            voice_channel = guild.get_channel(vch.id)

        avatar = await self.member_avatar(gid, ctx.user_id)
        _, info = await worker.enqueue(guild, q, ctx.name or "網頁後台", voice_channel, when, avatar)
        return info

    def _target_channel(self, gid: int, channel_id: int):
        """要把歌放進指定頻道：該頻道已有播放器就用它，沒有就預約一個閒置的
        回傳 (worker, guild, 頻道)，或一段錯誤訊息（str）

        Put a song into a specific channel: reuse the player already there, otherwise reserve an idle one.
        Returns ``(worker, guild, channel)`` or an error message (``str``).
        """
        for p in self.players(gid):
            if (p.vc and p.vc.channel.id == channel_id) or (p.state.reserved and p.state.reserved_channel == channel_id):
                return p.worker, p.guild, p.guild.get_channel(channel_id)
        if self.at_stream_limit():
            return self.all_busy_message(gid)
        for p in self.players(gid):
            if not p.vc and not p.state.busy:
                ch = p.guild.get_channel(channel_id)
                if ch is None:
                    return "找不到這個語音頻道（機器人可能看不到它）"
                p.worker.reserve(gid, channel_id)
                return p.worker, p.guild, ch
        return self.all_busy_message(gid)
