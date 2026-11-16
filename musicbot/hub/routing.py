"""挑播放器：這個人現在該用哪個機器人、能不能控制

Picking players: which bot a person should use right now, and whether they may control it
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .models import Player, UserCtx

if TYPE_CHECKING:
    pass


class RoutingMixin:
    def players(self, gid: int) -> list[Player]:
        """這個伺服器裡所有的播放器（含閒置的分身）

        Every player in this server (idle clones included).
        """
        return [Player(w, g) for w in self.workers if (g := w.get_guild(gid))]

    def active_players(self, gid: int) -> list[Player]:
        """正在使用中的播放器：已在語音頻道，或有待播曲目

        Players in use: already in a voice channel, or holding queued tracks.
        """
        return [p for p in self.players(gid) if p.vc or p.state.busy]

    def player_by_pid(self, gid: int, pid: str | None) -> Player | None:
        """依播放器 id 找播放器 / Find a player by its id."""
        return next((p for p in self.players(gid) if p.pid == pid), None) if pid else None

    def voice_channel_of(self, gid: int, user_id: int | None):
        """這個使用者目前所在的語音頻道（不在任何頻道回傳 None）

        The voice channel this user is in right now (None when they are in no channel).
        """
        if user_id is None:
            return None
        for w in self.workers:
            g = w.get_guild(gid)
            if g is None:
                continue
            for ch in [*g.voice_channels, *g.stage_channels]:
                if any(m.id == user_id for m in ch.members):
                    return ch
            return None
        return None

    def default_player(self, gid: int, ctx: UserCtx) -> Player | None:
        """沒指定播放器時：優先用"使用者所在頻道裡的那個"，否則第一個使用中的

        When no player was chosen: prefer the one in the user's own channel, otherwise the first player in use.
        """
        active = self.active_players(gid)
        vch = self.voice_channel_of(gid, ctx.user_id)
        if vch:
            for p in active:
                if p.vc and p.vc.channel.id == vch.id:
                    return p
        return active[0] if active else None

    def resolve_player(self, gid: int, ctx: UserCtx, pid: str | None) -> Player | None:
        """明確指定的播放器優先，否則用預設的 / An explicitly chosen player wins, else the default one."""
        return self.player_by_pid(gid, pid) or self.default_player(gid, ctx)

    def pick_for_user(self, gid: int, user_id: int | None, create: bool = False):
        """依使用者所在的語音頻道選播放器，回傳 (worker, guild, 使用者所在頻道)
        頻道裡已有播放器就用它；沒有且 create=True 時，派一個閒置的分身（找不到就是 None）

        Pick a player for a user based on the voice channel they are in. Returns ``(worker, guild, channel)``.
        A player already in that channel is reused; otherwise, when ``create=True``, an idle clone is assigned
        (``worker`` is None when none is free).
        """
        vch = self.voice_channel_of(gid, user_id)
        if vch is None:
            return None, None, None
        for p in self.players(gid):
            # 已經在這個頻道，或已被預約要去這個頻道（同一頻道的人同時加歌，共用同一個播放器）
            # Already in this channel, or reserved for it (people in the same channel adding songs at once share one player).
            if (p.vc and p.vc.channel.id == vch.id) or (p.state.reserved and p.state.reserved_channel == vch.id):
                return p.worker, p.guild, vch
        if create and not self.at_stream_limit():
            for p in self.players(gid):          # 主機器人排第一，優先使用 / the main bot comes first, so it is preferred
                if not p.vc and not p.state.busy:
                    p.worker.reserve(gid, vch.id)   # 立刻預約：解析網址要幾秒，期間不能被別的頻道的人搶走 / reserve at once: resolving takes seconds and nobody from another channel may steal it
                    return p.worker, p.guild, vch
        return None, None, vch

    def can_control(self, ctx: UserCtx, gid: int, player: Player | None) -> tuple[bool, str | None]:
        """這個人能不能控制這個播放器？回傳 (可以嗎, 不行的原因)

        May this person control this player? Returns ``(allowed, reason if not)``.
        """
        if ctx.pending:
            return False, "請用 /help 的專屬連結進來"
        if ctx.is_host or self.free_control:    # 開放／驗證模式：進得來的人都能控制所有頻道 / open/verify mode: anyone who gets in controls every channel
            return True, None
        vch = self.voice_channel_of(gid, ctx.user_id)
        if vch is None:
            return False, "請先加入語音頻道，才能控制播放（現在是唯讀）"
        if player and player.vc and player.vc.channel.id != vch.id:
            return False, f"這個播放器在「{player.vc.channel.name}」，請先加入那個頻道才能控制它"
        return True, None

    def channel_list(self, gid: int) -> list[dict]:
        """伺服器的語音頻道，以及各頻道目前有沒有播放器（讓看板可以選"要把歌加到哪個頻道"）

        The server's voice channels and which player (if any) sits in each, so the dashboard can offer
        "add songs to which channel".
        """
        players = self.players(gid)
        if not players:
            return []
        by_channel = {p.vc.channel.id: p.pid for p in players if p.vc}
        out = []
        for ch in [*players[0].guild.voice_channels, *players[0].guild.stage_channels]:
            out.append({
                "id": str(ch.id), "name": ch.name,
                "members": sum(1 for m in ch.members if not m.bot),
                "pid": by_channel.get(ch.id),
            })
        return out
