"""我的歌單的網頁操作：存歌單、建資料夾、搬移、刪除、播放（含資料夾循環）

身分：用 Discord 使用者 id 當帳號（從 /help 的連結進來就有）；本機直接開看板的人就是主人，用擁有者的歌單
歌單只在這台電腦上，不會傳到中繼站；每個人只看得到、也只能動自己的

The library actions of the dashboard: save playlists, make folders, move, delete, play (including folder loops).
Identity: the Discord user id is the account (anyone who came in through the /help link has one); the local machine counts as the
owner and uses the owner's library. Everything stays on this machine (the relay never sees it) and everyone sees and edits only their own.
"""
from __future__ import annotations

import asyncio
import logging

from ..library import Library, LibraryError, tree
from ..sources import resolve_tracks
from .models import UserCtx

log = logging.getLogger("musicbot")

PLAY_WHEN = ("end", "next", "now", "replace")      # 加到最後｜下一首｜立刻｜取代整個待播 / append | next | now | replace the whole queue
SCOPES = ("off", "folder", "folders")              # 不循環｜資料夾循環｜跨資料夾循環 / no loop | loop the folder | loop across sibling folders


class LibraryMixin:
    """Hub 的歌單功能（由 core.py 組進 Hub）/ The Hub's library features (assembled into Hub by core.py)."""
    library: Library

    def library_user(self, ctx: UserCtx) -> str | None:
        """這個人的歌單帳號；沒有身分（還沒用連結確認）就是 None / This person's library key; None without an identity."""
        if ctx.user_id is not None:
            return str(ctx.user_id)
        if ctx.is_host:
            return str(min(self.owner_ids)) if self.owner_ids else "host"
        return None

    def library_outline(self, user: str) -> dict:
        """給網頁的整棵樹摘要 / The outline of the whole tree for the page."""
        return tree.outline(self.library.root(user))

    def library_songs(self, user: str, node_id: str, offset: int = 0) -> dict:
        """打開一張歌單：一次送 LIB_SONGS_PER_SEND 首（往下捲再要）/ Open a playlist: sent LIB_SONGS_PER_SEND at a time (more on scroll)."""
        from .. import params
        node = tree.find(self.library.root(user), node_id)
        if node is None:
            raise LibraryError("找不到這個項目")
        songs = tree.songs_of(node)
        offset = max(0, int(offset))
        return {"id": node_id, "type": node["type"], "name": node["name"], "total": len(songs), "offset": offset,
                "songs": songs[offset: offset + params.LIB_SONGS_PER_SEND]}

    @staticmethod
    def _track_songs(player, ids: list) -> list[dict]:
        """待播清單裡這些 id 的歌（沒指定就是整份待播，含正在播的）/ The queued songs with these ids (the whole queue incl. the current song when none are given)."""
        st = player.worker.state(player.guild.id)
        pool = ([st.current] if st.current else []) + list(st.queue)
        want = set(map(str, ids or ()))
        picked = [t for t in pool if not want or t.id in want]
        return [{"url": t.url, "title": t.title, "duration": t.duration, "thumbnail": t.thumbnail,
                 "uploader": t.uploader, "search": t.search} for t in picked]

    async def library_action(self, gid: int, ctx: UserCtx, pid: str | None, msg: dict) -> tuple[str | None, dict | None]:
        """處理一個 lib_ 操作，回傳（要顯示的提示, 要回給這個瀏覽器的訊息）

        Handle one lib_ action; returns ``(toast text, message to send back to this browser)``.
        """
        user = self.library_user(ctx)
        if user is None:
            return "請先用 /help 的專屬連結進來", None
        root = self.library.root(user)
        t = str(msg.get("type"))
        text = lambda k, n=200: str(msg.get(k) or "")[:n]       # noqa: E731 - 取文字欄位並限制長度 / a text field, length-limited
        ids = [str(i) for i in (msg.get("ids") or []) if isinstance(i, (str, int))][:5000]
        changed, note = True, None
        try:
            if t == "lib_get":
                changed = False
            elif t == "lib_open":
                return None, {"type": "library_songs", "data": self.library_songs(user, text("id"), msg.get("offset", 0) if isinstance(msg.get("offset", 0), int) else 0)}
            elif t in ("lib_save", "lib_add"):
                player = self.resolve_player(gid, ctx, pid)
                if player is None:
                    return "目前沒有播放器，沒有可以存的歌", None
                songs = self._track_songs(player, ids)
                if not songs:
                    return "待播清單是空的", None
                if t == "lib_save":
                    node = tree.add_playlist(root, text("parent") or "root", text("name", 80), songs)
                    note = f"已存成歌單「{node['name']}」（{len(node['songs'])} 首）"
                else:
                    n = tree.add_songs(root, text("playlist"), songs)
                    note = f"已加入 {n} 首"
            elif t == "lib_add_link":
                query = text("url", 500).strip()
                if not query:
                    return "請貼上歌曲或歌單的連結", None
                found = await asyncio.to_thread(resolve_tracks, query, ctx.name or "")
                songs = [{"url": x.url, "title": x.title, "duration": x.duration, "thumbnail": x.thumbnail, "uploader": x.uploader, "search": x.search} for x in found]
                if not songs:
                    return "找不到可以存的內容", None
                if msg.get("playlist"):
                    n = tree.add_songs(root, text("playlist"), songs)
                else:
                    n = len(tree.add_playlist(root, text("parent") or "root", text("name", 80), songs)["songs"])
                note = f"已存 {n} 首"
            elif t == "lib_folder":
                if ids:
                    folder = tree.group(root, ids, text("name", 80))
                else:
                    folder = tree.add_folder(root, text("parent") or "root", text("name", 80))
                note = f"已建立資料夾「{folder['name']}」"
            elif t == "lib_playlist":
                node = tree.add_playlist(root, text("parent") or "root", text("name", 80), [])
                note = f"已建立歌單「{node['name']}」"
            elif t == "lib_rename":
                tree.rename(root, text("id"), text("name", 80))
            elif t == "lib_delete":
                note = f"已刪除 {tree.delete(root, ids)} 個項目"
            elif t == "lib_move":
                at = msg.get("index")
                note = f"已搬移 {tree.move(root, ids, text('to') or 'root', at if isinstance(at, int) and not isinstance(at, bool) else None)} 個項目"
            elif t == "lib_song_move":
                n = tree.move_songs(root, text("playlist"), [i for i in (msg.get("indexes") or []) if isinstance(i, int)][:5000], text("to"))
                note = f"已搬 {n} 首歌" if n else None
            elif t == "lib_song_order":
                frm, to = msg.get("from"), msg.get("to")
                if isinstance(frm, int) and isinstance(to, int):
                    tree.reorder_song(root, text("playlist"), frm, to)
            elif t == "lib_remove_songs":
                tree.remove_songs(root, text("playlist"), [i for i in (msg.get("indexes") or []) if isinstance(i, int)][:5000])
            elif t == "lib_play":
                return await self._library_play(gid, ctx, pid, user, msg), None
            else:
                return None, None
        except LibraryError as exc:
            return str(exc), None
        if changed:
            self.library.save()
        reply = {"type": "library", "data": {"tree": self.library_outline(user)}}
        return note, reply

    async def _library_play(self, gid: int, ctx: UserCtx, pid: str | None, user: str, msg: dict) -> str | None:
        """播放一個資料夾／歌單：把裡面的歌放進待播，scope 決定播完怎麼辦

        Play a folder / playlist: its songs go into the queue; ``scope`` decides what happens when they run out.
        """
        node = tree.find(self.library.root(user), str(msg.get("id") or ""))
        if node is None:
            return "找不到這個項目"
        when = msg.get("when") if msg.get("when") in PLAY_WHEN else "end"
        scope = msg.get("scope") if msg.get("scope") in SCOPES else "off"
        songs = tree.songs_of(node)
        if not songs:
            return "這裡面還沒有歌"
        target = self._pick_target(gid, ctx, pid, msg)
        if isinstance(target, str):
            return target
        worker, guild, voice_channel = target
        avatar = await self.member_avatar(gid, ctx.user_id)
        st = worker.state(guild.id)
        if when == "replace":
            worker.clear_queue(guild.id)
            when = "end"
        tracks = worker.tracks_from_songs(songs, ctx.name or "網頁後台", avatar)
        # 資料夾循環只對資料夾有意義；歌單播完就是播完 / looping only makes sense for a folder; a playlist just ends
        st.scope = ({"mode": scope, "user": user, "node": node["id"], "name": ctx.name or "", "avatar": avatar}
                    if scope != "off" and node["type"] == "folder" else None)
        _, info = await worker.enqueue_tracks(guild, tracks, voice_channel, when)
        return info or f"已加入「{node['name']}」（{len(tracks)} 首）"

    def library_refill(self, scope: dict) -> list[dict] | None:
        """待播清單播完時，資料夾循環要接著放哪些歌；回傳歌的清單並更新 scope，找不到了回傳 None

        What a folder loop puts into the queue when it runs out; returns the songs and updates ``scope`` (None when the folder is gone).
        """
        root = self.library.root(scope["user"])
        node = tree.find(root, scope["node"])
        if node is None:
            return None
        if scope["mode"] == "folders":
            seen = {node["id"]}                                   # 下一個資料夾若是空的就跳過；繞一圈都沒有歌才結束 / skip empty folders; stop only after a full round without songs
            while True:
                nxt = tree.next_sibling_folder(root, node["id"])
                if nxt is None or nxt["id"] in seen:
                    break
                node = nxt
                scope["node"] = node["id"]
                if tree.songs_of(node):
                    break
                seen.add(node["id"])
        songs = tree.songs_of(node)
        return songs or None
