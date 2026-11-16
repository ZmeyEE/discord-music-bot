"""給網頁的完整狀態，與音質設定

The full state sent to a browser, and the quality setting
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .. import bilibili, config, params
from .models import _EMPTY_PLAYER, UserCtx

if TYPE_CHECKING:
    pass
log = logging.getLogger("musicbot")


class SnapshotMixin:
    def snapshot(self, gid: int, ctx: UserCtx, pid: str | None, cache: dict | None = None) -> dict | None:
        """給一個瀏覽器的完整狀態，cache：同一次廣播給多個瀏覽器時共用的暫存，
        與"這個人是誰"無關的部分（播放器摘要、頻道清單、佇列）只算一次

        The full state for one browser. ``cache`` is shared across the browsers of one broadcast so the
        parts that don't depend on who is looking (player summary, channel list, queue) are computed once.
        Returns None when the bot isn't in that server.
        """
        cache = {} if cache is None else cache
        players = self.players(gid)
        if not players:
            return None
        guild = players[0].guild
        if ctx.pending:   # 還沒驗證：只給最少的資訊（伺服器名稱），不洩漏任何播放內容 / not verified yet: give the bare minimum (server name) and leak no playback info
            return {
                "guild": {"id": str(gid), "name": guild.name}, "access": self.mode,
                "me": {"name": ctx.name, "host": False, "owner": False, "pending": True, "can_control": False,
                       "voice": None, "reason": "請用 /help 的專屬連結進來"},
            }
        selected = self.resolve_player(gid, ctx, pid)
        active = self.active_players(gid)
        ok, reason = self.can_control(ctx, gid, selected)
        vch = self.voice_channel_of(gid, ctx.user_id)

        summary = cache.get(("summary", gid))
        if summary is None:
            summary = cache[("summary", gid)] = [{
                "pid": p.pid,
                "name": p.vc.channel.name if p.vc else p.worker.label,
                "bot": p.worker.label,
                "title": ((p.state.current.title or p.state.current.url) if p.state.current else None),
                "paused": bool(p.vc and p.vc.is_paused()),
            } for p in active]
        if selected is None:
            state = _EMPTY_PLAYER
        else:
            state = cache.get(("player", selected.pid))
            if state is None:
                state = cache[("player", selected.pid)] = selected.worker.player_state(selected.guild)
        channels = cache.get(("channels", gid))
        if channels is None:
            channels = cache[("channels", gid)] = self.channel_list(gid)

        acc = bilibili.remembered_account()
        bili = {"logged_in": bool(acc), "can_manage": ctx.is_host or ctx.is_owner}
        if acc and bili["can_manage"]:
            bili |= {k: acc.get(k) for k in ("name", "face", "vip", "vip_label")}   # 帳號細節只給有權管理的人 / account details only for people allowed to manage it

        return {
            "guild": {"id": str(gid), "name": guild.name},
            "players": summary,
            "selected": selected.pid if selected else None,
            "clones": {"total": len(players), "idle": len(players) - len(active)},
            "limit": {"max": self.stream_limit, "cap": len(self.workers), "reached": self.at_stream_limit(),
                      "notice": self.stream_notice},
            "channels": channels,
            "access": self.mode,
            "me": {
                "name": ctx.name, "host": ctx.is_host, "owner": ctx.is_owner, "pending": False,
                "voice": vch.name if vch else None, "can_control": ok, "reason": reason,
            },
            "bili": bili,
            "quality": {"kbps": config.quality_for(gid), "choices": list(params.QUALITY_CHOICES)},
            **state,
        }

    def set_quality(self, gid: int, kbps: int) -> bool:
        """切換該伺服器的 Opus 位元率並存檔；正在播放的曲目從原位置重新開始，讓新音質立刻生效（方便 A/B 比較）

        Switch a server's Opus bitrate and save it; the song that is playing restarts from its current
        position so the new quality is heard at once (handy for A/B comparison).
        """
        if not config.set_quality_for(gid, kbps):
            return False
        log.info("伺服器 %s 音質切換為 Opus %d kbps", gid, kbps)
        for p in self.players(gid):
            p.worker.restart_current(p.guild)
        self.notify(gid)
        return True
