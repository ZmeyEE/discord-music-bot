"""狀態快照：整理成可送給網頁的字典

State snapshot: a dict ready to send to the web dashboard
"""
from __future__ import annotations

import itertools
from typing import TYPE_CHECKING

import discord

from .. import params

if TYPE_CHECKING:
    pass


class SnapshotMixin:
    # 單一播放器；權限與多播放器資訊由 Hub 加上
    # For a single player; permissions and multi-player info are added by the Hub.
    def player_state(self, guild: discord.Guild, limit: int | None = None) -> dict:
        """這個播放器在該伺服器的狀態，整理成可送給前端的字典

        This player's state in a server as a dict ready to send to the front-end.
        ``limit`` = 待播清單只給前幾首（一個瀏覽器的視窗大小）；``queue_sig`` 是這幾首的指紋，只在伺服器內部用
        ``limit`` = how many queued songs to include (one browser's window). ``queue_sig`` fingerprints that window and stays server-side.
        """
        st = self.state(guild.id)
        vc = guild.voice_client
        window = list(itertools.islice(st.queue, min(limit or params.QUEUE_VIEW, params.QUEUE_VIEW)))
        cur = None
        if st.current:
            cur = st.current.public() | {
                "quality": st.stream.quality if st.stream else "",
                "bitrate": st.bitrate_kbps,
                "position": round(st.position(), 1),
                "loading": st.stream is None,
            }
        return {
            "connected": bool(vc),
            "channel": vc.channel.name if vc else None,
            "paused": bool(vc and vc.is_paused()),
            "loop": st.loop,
            "current": cur,
            "queue": [t.public() for t in window],
            "queue_total": len(st.queue),
            "queue_sig": hash(tuple(t.signature() for t in window)),
        }
