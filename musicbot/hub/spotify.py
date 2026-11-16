"""Spotify 帳號連結的網頁操作：連結、貼回授權網址、登出、列出自己的歌單、匯入成我的歌單

流程：按"前往授權"(sp_connect) → 在 Spotify 同意 → 瀏覽器被導向設定的 redirect 網址（朋友的電腦打不開那頁沒關係）→ 把網址列整段貼回來(sp_finish)
所以不管是本機還是經過中繼站，都不需要讓 Spotify 連得到家裡的電腦

Dashboard actions for the Spotify link: connect, paste the authorisation address back, log out, list one's own playlists, import one as a library playlist.
Flow: "go authorise" (sp_connect) -> agree at Spotify -> the browser is sent to the configured redirect address (it is fine if it fails to open on a friend's
computer) -> paste the whole address-bar text back (sp_finish). So neither the local machine nor the relay needs to be reachable by Spotify.
"""
from __future__ import annotations

import logging
import os
import time

import aiohttp

from ..library import LibraryError, tree
from ..spotify import Accounts, SpotifyError, client
from .models import UserCtx

log = logging.getLogger("musicbot")


class SpotifyMixin:
    """Hub 的 Spotify 功能（由 core.py 組進 Hub）/ The Hub's Spotify features (assembled into Hub by core.py)."""
    spotify: Accounts

    @staticmethod
    def spotify_client_id() -> str:
        """.env 的 SPOTIFY_CLIENT_ID；空的代表沒設定，畫面上就不提供連結 / SPOTIFY_CLIENT_ID in .env; empty = not configured, so the screen offers no link."""
        return os.environ.get("SPOTIFY_CLIENT_ID", "").strip()

    def spotify_redirect(self) -> str:
        """授權完要導回的網址，必須和 Spotify 開發者後台登記的一模一樣 / The address to come back to; it must match the one registered in Spotify's developer dashboard exactly."""
        configured = os.environ.get("SPOTIFY_REDIRECT_URI", "").strip()
        return configured or f"http://127.0.0.1:{os.environ.get('DASHBOARD_PORT', '8765')}/spotify/callback"

    def spotify_status(self, user: str) -> dict:
        """給網頁的狀態：有沒有設定、有沒有連結 / The state for the page: configured or not, linked or not."""
        acc = self.spotify.users.get(user)
        return {"enabled": bool(self.spotify_client_id()), "linked": bool(acc), "name": (acc or {}).get("name", ""), "redirect": self.spotify_redirect()}

    async def _spotify_access(self, session: aiohttp.ClientSession, user: str) -> str:
        """這個人目前可用的 access token；快過期就先續期 / A usable access token for this person; refreshed first when it is about to expire."""
        acc = self.spotify.users.get(user)
        if not acc:
            raise SpotifyError("還沒連結 Spotify 帳號")
        if acc["expires"] <= time.time():
            fresh = await client.refresh(session, self.spotify_client_id(), acc["refresh"])
            self.spotify.users[user] = {**acc, **fresh}
            self.spotify.save()
        return self.spotify.users[user]["access"]

    async def _spotify_call(self, user: str, fn):
        """用 fn(session, access) 呼叫 Spotify；遇到憑證過期就續期後再試一次 / Call Spotify with fn(session, access); on an expired token refresh it and try once more."""
        async with aiohttp.ClientSession() as session:
            try:
                return await fn(session, await self._spotify_access(session, user))
            except SpotifyError as exc:
                if str(exc) != "expired":
                    raise
                acc = self.spotify.users[user]
                self.spotify.users[user] = {**acc, **await client.refresh(session, self.spotify_client_id(), acc["refresh"])}
                self.spotify.save()
                return await fn(session, self.spotify.users[user]["access"])

    async def spotify_action(self, ctx: UserCtx, msg: dict) -> tuple[str | None, dict | None]:
        """處理一個 sp_ 操作，回傳（提示, 回給這個瀏覽器的訊息）/ Handle one sp_ action: ``(toast, message back to this browser)``."""
        user = self.library_user(ctx)
        if user is None:
            return "請先用 /help 的專屬連結進來", None
        t = str(msg.get("type"))
        status = lambda extra=None: {"type": "spotify", "data": {**self.spotify_status(user), **(extra or {})}}   # noqa: E731
        if t == "sp_status":
            return None, status()
        if not self.spotify_client_id():
            return "這個機器人還沒有設定 Spotify（.env 的 SPOTIFY_CLIENT_ID）", status()
        try:
            if t == "sp_connect":
                verifier, challenge = client.new_pkce()
                state = self.spotify.begin(user, verifier)
                return None, status({"auth_url": client.auth_url(self.spotify_client_id(), self.spotify_redirect(), state, challenge)})
            if t == "sp_finish":
                code, state = client.parse_redirect(str(msg.get("text") or "")[:4000])
                verifier = self.spotify.finish(user, state)
                if verifier is None:
                    return "這次授權已經過期或不是你發起的，請再按一次「前往授權」", status()
                async with aiohttp.ClientSession() as session:
                    tokens = await client.exchange(session, self.spotify_client_id(), self.spotify_redirect(), code, verifier)
                    me = await client.get(session, tokens["access"], "/me")
                name = me.get("display_name") or me.get("id") or "Spotify"
                self.spotify.link(user, tokens, str(name)[:60])
                return f"已連結 Spotify 帳號：{name}", status()
            if t == "sp_logout":
                self.spotify.unlink(user)
                return "已登出 Spotify（這台機器上的憑證已刪除）", status()
            if t == "sp_playlists":
                if user not in self.spotify.users:
                    return "還沒連結 Spotify 帳號", status()
                rows = await self._spotify_call(user, client.list_playlists)
                return None, status({"playlists": rows})
            if t == "sp_import":
                pid = str(msg.get("id") or "")[:64]
                songs = await self._spotify_call(user, lambda s, a: client.playlist_songs(s, a, pid))
                if not songs:
                    return "這張歌單沒有可以匯入的歌（Spotify 開發模式只讀得到自己建立或共同編輯的歌單）", status()
                root = self.library.root(user)
                node = tree.add_playlist(root, str(msg.get("parent") or "root"), str(msg.get("name") or "")[:80] or "Spotify", songs)
                self.library.save()
                return f"已存成歌單「{node['name']}」（{len(node['songs'])} 首）", {"type": "library", "data": {"tree": self.library_outline(user)}}
        except (SpotifyError, LibraryError) as exc:
            if str(exc) == "expired":
                self.spotify.unlink(user)
                return "Spotify 的授權失效了，請重新連結", status()
            return str(exc), status()
        return None, None
