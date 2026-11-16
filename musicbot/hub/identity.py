"""身分：看板連結、誰是誰、裝置憑證

Identity: dashboard links, who is who, device tokens
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

import discord

from .. import auth
from .models import UserCtx

if TYPE_CHECKING:
    pass


class IdentityMixin:
    def link_for(self, guild_id: int, user_id: int, name: str) -> str:
        """這個人專屬的後台連結（簽章憑證綁定他的 Discord 身分，12 小時有效）

        A personal dashboard link for this person (the signed token is bound to their Discord identity, valid 12 h).
        """
        return f"{self.base_url}/g/{guild_id}?t={auth.make_token(self.secret, guild_id, user_id, name)}"

    def guild_url(self, guild_id: int) -> str:
        """所有人共用的看板網址（開放模式不需要各自的連結）

        The shared dashboard URL (open mode doesn't need personal links).
        """
        return f"{self.base_url}/g/{guild_id}"

    def guild_list(self) -> list[dict]:
        """主機器人所在的伺服器清單（給 /api/guilds 與中繼站） / The servers the main bot is in (for /api/guilds and the relay)."""
        return [{"id": str(g.id), "name": g.name} for g in self.primary.guilds]

    def ctx_from_token(self, identity: auth.Identity) -> UserCtx:
        """把驗證過的連結憑證變成身分 / Turn a verified link token into an identity."""
        return UserCtx(identity.user_id, identity.name, is_owner=identity.user_id in self.owner_ids, via="link")

    @staticmethod
    def guest_ctx(name: str) -> UserCtx:
        """開放模式下沒帶憑證的訪客：能控制播放，但不是擁有者（不能動 Bilibili 帳號）

        A guest without a token in open mode: may control playback but is not an owner (can't touch the Bilibili account).
        """
        return UserCtx(None, name or "訪客", via="guest")

    @staticmethod
    def pending_ctx() -> UserCtx:
        """驗證模式下尚未驗證的人：什麼都不能做 / Someone not yet verified in verify mode: can do nothing."""
        return UserCtx(None, "未驗證", pending=True, via="pending")

    @staticmethod
    def host_ctx() -> UserCtx:
        """直接在本地開看板的人：等同擁有者 / Someone opening the dashboard on the local machine: equivalent to the owner."""
        return UserCtx(None, "網頁後台", is_host=True, is_owner=True, via="local")

    async def member_name(self, gid: int, uid: int, fallback: str = "") -> str | None:
        """這個人現在還在伺服器裡嗎？在的話回傳他目前的顯示名稱（真實暱稱）；不在回傳 None
        用 REST 查詢（不需要特權 intent），結果快取 10 分鐘；Discord 暫時查不到時沿用登錄的名字，不鎖人在外面

        Is this person still in the server? If so return their current display name (real nickname); else None.
        Uses a REST lookup (no privileged intent needed) cached for 10 minutes. When Discord can't be reached
        temporarily, the registered name is reused so nobody gets locked out.
        """
        key = (gid, uid)
        hit = self._member_cache.get(key)
        if hit and time.monotonic() - hit[0] < 600:
            return hit[1]
        guild = self.primary.get_guild(gid)
        if guild is None:
            return fallback or None
        try:
            member = await guild.fetch_member(uid)
            name = member.display_name
            av = getattr(member, "display_avatar", None)        # 伺服器專屬頭像優先，沒有就用帳號頭像 / the server-specific avatar wins, else the account avatar
            self._avatar_cache[key] = av.with_size(64).url if av else ""
        except discord.NotFound:
            name = None
        except discord.HTTPException:
            return fallback or None
        self._member_cache[key] = (time.monotonic(), name)
        return name

    async def member_avatar(self, gid: int, uid: int | None) -> str:
        """點歌者的頭像網址（64px）；查不到（訪客、本地、暫時連不上 Discord）回傳空字串

        The requester's avatar URL (64 px); an empty string when unknown (guest, local, Discord unreachable).
        """
        if not uid:
            return ""
        await self.member_name(gid, uid)          # 沿用同一份 10 分鐘快取，不會每次點歌都打 Discord / reuses the same 10-minute cache, so we don't hit Discord on every request
        return self._avatar_cache.get((gid, uid), "")

    def issue_device(self, ctx: UserCtx, gid: int) -> str:
        """替一個已確認身分的人登記這個瀏覽器（之後不用再驗證），回傳要存在瀏覽器的憑證

        Register this browser for someone whose identity is confirmed (no re-verification needed later).
        Returns the token the browser should store.
        """
        return self.members.add_device(ctx.user_id, ctx.name, gid)

    def revoke_user(self, uid: int) -> int:
        """撤銷一個人所有已記住的裝置；正在連線的瀏覽器會立刻回到未驗證

        Revoke all remembered devices of a person; browsers currently connected fall back to "unverified" at once.
        """
        n = self.members.revoke_user(uid)
        for key in [k for k in self._member_cache if k[1] == uid]:
            del self._member_cache[key]
        self.core.demote(uid)
        return n

    @staticmethod
    def is_owner(ctx: UserCtx) -> bool:
        """本地或機器人擁有者才算擁有者權限 / Owner rights belong to the local machine and the bot's owners."""
        return ctx.is_host or ctx.is_owner
