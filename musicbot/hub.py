"""Hub：協調所有播放器（主機器人＋分身），決定"誰能控制什麼"

三件事：
1. 路由：使用者在哪個語音頻道，就操作那個頻道裡的播放器；該頻道還沒有播放器，就派一個閒置的分身進去
2. 權限：只有"人在語音頻道裡"的人能控制播放（其他人唯讀）；更換 Bilibili 帳號只限機器人擁有者／本地
3. 快照／動作：後台與指令共用同一套邏輯

Hub: coordinates every player (main bot + clones) and decides "who may control what".

Three jobs:
1. Routing: a user operates the player that sits in the voice channel they are in; if that channel has no
   player yet, an idle clone is sent in.
2. Permissions: in "voice" mode only people inside a voice channel can control playback (everyone else is
   read-only); switching the Bilibili account is limited to the bot owner / the local machine.
3. Snapshots / actions: the dashboard and the slash commands share the same logic.

File map / 檔案地圖 (search for the banner comments):
  基本 Basics -> 已記住的裝置 Remembered devices -> 事件 Events -> 路由 Routing -> 同時播放數 Stream limit
  -> 權限 Permissions -> 快照 Snapshot -> 音質 Quality -> 動作 Actions -> Bilibili 帳號 Bilibili account
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Awaitable, Callable, NamedTuple

import discord

from . import auth, bilibili, config, sources
from .config import QUALITY_CHOICES
from .health import HOLD_SECONDS
from .members import Registry
from .paths import MEMBERS_FILE
from .player import PlayerBot

if TYPE_CHECKING:
    from .dashboard import Dashboard

log = logging.getLogger("musicbot")

Emit = Callable[[dict], Awaitable[None]]   # 把訊息只傳給"發出請求的那個瀏覽器"/ send a message to only the browser that made the request


# ============================================================
# 資料結構 / Data structures
# ============================================================
@dataclass(frozen=True)
class UserCtx:
    """後台連線者的身分

    Who a dashboard connection is (identity + privileges).
    """
    user_id: int | None        # Discord 使用者 ID；本地直接開的後台沒有 / Discord user id; None for the local dashboard
    name: str
    is_host: bool = False      # 從執行機器人的這台電腦直接開（localhost）/ opened directly on the machine running the bot (localhost)
    is_owner: bool = False     # 機器人（應用程式）的擁有者 / the owner of the bot application
    pending: bool = False      # 驗證模式：還沒用 /help 的專屬連結確認身分（什麼都不能做，只會看到"請用連結進來"）/ verify mode: identity not yet confirmed via the /help link (nothing allowed; only sees "use the link")
    via: str = ""              # 身分從哪來：device（記住的裝置）／link（/help 的連結）／local／guest／pending / where the identity came from: device (remembered) / link (/help) / local / guest / pending


class Player(NamedTuple):
    """一個"機器人帳號 × 伺服器"的組合，附帶幾個方便的屬性

    A (bot account, server) pair with a few convenience properties.
    """
    worker: PlayerBot
    guild: discord.Guild

    @property
    def pid(self) -> str:
        return self.worker.pid

    @property
    def vc(self):
        """該伺服器裡這個機器人的語音連線（沒在語音頻道就是 None） / This bot's voice connection in that server (None when not in voice)."""
        return self.guild.voice_client

    @property
    def state(self):
        return self.worker.state(self.guild.id)


_EMPTY_PLAYER = {"connected": False, "channel": None, "paused": False, "loop": "off", "current": None, "queue": []}   # 沒有播放器時給前端的空狀態 / the empty state sent to the front-end when no player is selected


class Hub:
    """所有播放器的總指揮

    The conductor of all players. One Hub exists per process.
    """

    def __init__(self) -> None:
        self.workers: list[PlayerBot] = []
        self.dashboard: "Dashboard | None" = None
        self._core = None
        self.base_url = ""
        self.owner_ids: set[int] = set()
        self.secret = config.dashboard_secret()
        self.mode = config.dashboard_mode()                 # open / verify / voice
        self.open_access = self.mode == "open"              # 任何人都能進（也決定 /api/guilds 要不要公開）/ anyone may enter (also decides whether /api/guilds is public)
        self.free_control = self.mode != "voice"            # 進得來的人可以控制所有頻道（語音模式才限制在自己的頻道）/ whoever gets in may control every channel (only voice mode restricts to your own channel)
        self.members = Registry(MEMBERS_FILE)               # 驗證過的成員與裝置（存在這台電腦）/ verified members and devices (stored on this machine)
        self._member_cache: dict[tuple[int, int], tuple[float, str | None]] = {}
        self._avatar_cache: dict[tuple[int, int], str] = {}
        self._ceiling: int | None = None                    # 卡頓偵測停掉頻道後，暫時壓住的同時播放數 / the temporary cap on simultaneous streams after the stutter detector removed one
        self._ceiling_until = 0.0                           # ……壓到什麼時候（monotonic）/ ...until when (monotonic)
        self.limit_notice: dict | None = None               # 最近一次停止頻道的公告（看板橫幅用）/ the latest "channel stopped" announcement (dashboard banner)

    # ============================================================
    # 基本 / Basics
    # ============================================================
    @property
    def primary(self) -> PlayerBot:
        """主機器人（第一個帳號） / The main bot (the first account)."""
        return self.workers[0]

    @property
    def core(self):
        """看板核心（工作階段／權限／廣播），本地後台與遠端中繼站共用，延遲建立以避免循環匯入

        The dashboard core (sessions / permissions / broadcast), shared by the local dashboard and the
        remote relay. Created lazily to avoid a circular import.
        """
        if self._core is None:
            from .dashboard import DashboardCore
            self._core = DashboardCore(self)
        return self._core

    def notify(self, guild_id: int) -> None:
        """某個伺服器的狀態變了：請看板重新廣播 / A server's state changed: ask the dashboard to broadcast again."""
        if self._core is not None:
            self._core.broadcast(guild_id)

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

    # ============================================================
    # 已記住的裝置（verify 模式）/ Remembered devices (verify mode)
    # ============================================================
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

    # ============================================================
    # 事件 / Events
    # ============================================================
    async def on_worker_ready(self, worker: PlayerBot) -> None:
        """某個機器人登入完成，主機器人要查出擁有者並檢查 Bilibili 登入

        A bot finished logging in. The main bot looks up the owners and re-checks the Bilibili login.
        """
        if worker.is_primary:
            try:
                info = await worker.application_info()
                self.owner_ids = {info.owner.id} | {m.id for m in (info.team.members if info.team else [])}
            except discord.HTTPException as exc:
                log.warning("無法取得機器人擁有者資訊：%s", exc)
            asyncio.create_task(self.refresh_bili())

    async def on_guild_join(self, worker: PlayerBot, guild: discord.Guild) -> None:
        """主機器人被邀請進新伺服器時，在系統頻道丟一則快速上手說明

        When the main bot is invited to a new server, post a quick-start message in a channel it can write to.
        """
        if not worker.is_primary:
            return
        me = guild.me
        channel = guild.system_channel
        if not channel or not channel.permissions_for(me).send_messages:
            channel = next((c for c in guild.text_channels if c.permissions_for(me).send_messages), None)
        if channel:
            try:
                await channel.send(
                    "大家好！我是音樂機器人。\n"
                    "1. 先加入一個語音頻道\n"
                    "2. 輸入 `/play` 貼上 Bilibili／YouTube 網址、BV 號，或直接打關鍵字\n"
                    "3. 輸入 `/help` 取得你專屬的網頁控制看板連結（可拖曳排序、調音質）"
                )
            except discord.HTTPException:
                pass

    # ============================================================
    # 路由 / Routing
    # ============================================================
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

    # ============================================================
    # 同時播放的頻道數 / Simultaneous stream limit
    # ============================================================
    # 沒有固定上限；卡頓偵測停掉頻道後暫時壓低
    # There is no fixed limit; it is lowered temporarily after the stutter detector removes a channel.
    @property
    def stream_limit(self) -> int:
        """目前允許同時占用的串流數，平常 = 機器人帳號數（分身不設上限）；
        偵測到卡頓、停掉一個頻道後，HOLD_SECONDS 內暫時壓在"停掉後剩下的數量"，之後自動恢復

        How many streams may be occupied right now. Normally = the number of bot accounts (clones are
        unlimited). After the stutter detector stops a channel, it is held at "what remains" for
        HOLD_SECONDS and then recovers by itself.
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
        mins = int(HOLD_SECONDS // 60)
        text = (f"偵測到音樂卡頓，而且是從「{s.channel}」（{s.label}）加入之後才開始的"
                f"（它加入前的 {ev.base_seconds:.0f} 秒很順，加入後 {ev.recent_seconds:.0f} 秒內卡了 {ev.recent_events} 次）。"
                f"原因：{reason}。為了讓其他頻道維持順暢，已停止「{s.channel}」的播放並讓它離開"
                f"（它的待播清單已清空，想聽請稍後重新點歌）。目前還有 {removal.remaining} 個頻道在播放；"
                f"接下來 {mins} 分鐘內不再派新的頻道進來。如果仍然卡頓，會再次確認後繼續逐個停止。") if ev else \
               f"偵測到音樂卡頓（{reason}），已停止「{s.channel}」的播放。"
        self._ceiling, self._ceiling_until = removal.remaining, time.monotonic() + HOLD_SECONDS
        self.limit_notice = {"text": text, "at": time.time()}
        log.warning("播放卡頓：停止最後加入的頻道「%s」（%s），剩 %d 個；原因：%s", s.channel, s.label, removal.remaining, reason)
        targets = [g.voice_client.channel for w in self.workers for g in w.guilds if g.voice_client and g.voice_client.channel]
        await asyncio.wait_for(asyncio.gather(*(self._announce(ch, text) for ch in targets), return_exceptions=True), 8)
        await s.worker.stop(s.guild)
        self._notify_all()
        asyncio.get_running_loop().call_later(HOLD_SECONDS + 1, self._notify_all)   # 期滿時讓看板的公告自己消失 / when it expires, let the dashboard banner disappear by itself

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
            return (f"剛剛偵測到音樂卡頓、停止了最後加入的頻道，所以 {int(HOLD_SECONDS // 60)} 分鐘內暫時不再增加新的頻道"
                    f"（目前同時播放上限 {self.stream_limit} 個）。等其他頻道結束播放，或稍後再試。")
        n = len(self.players(gid))
        if n <= 1:
            return ("目前只有 1 個機器人帳號，而它正在另一個語音頻道播放。Discord 規定一個機器人在同一個伺服器只能待在一個語音頻道；"
                    "要多頻道同時播放，要有第 2 個機器人帳號：到 Developer Portal 建一個，再雙擊 add-clone.bat 貼上它的 Token（見 README「分身」）。")
        return f"這個伺服器的 {n} 個播放器都在使用中。等其中一個閒置，或用 add-clone.bat 再新增一個分身。"

    # ============================================================
    # 權限 / Permissions
    # ============================================================
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

    # ============================================================
    # 快照 / Snapshot
    # ============================================================
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
            "quality": {"kbps": config.quality_for(gid), "choices": list(QUALITY_CHOICES)},
            **state,
        }

    # ============================================================
    # 音質 / Audio quality
    # ============================================================
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

    # ============================================================
    # 動作 / Actions
    # ============================================================
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

    # ============================================================
    # Bilibili 帳號 / Bilibili account
    # ============================================================
    @staticmethod
    def is_owner(ctx: UserCtx) -> bool:
        """本地或機器人擁有者才算擁有者權限 / Owner rights belong to the local machine and the bot's owners."""
        return ctx.is_host or ctx.is_owner

    def _notify_all(self) -> None:
        """通知所有伺服器的看板重新整理 / Ask the dashboard of every server to refresh."""
        for g in self.primary.guilds:
            self.notify(g.id)

    async def refresh_bili(self) -> None:
        """啟動時確認已記住的 Bilibili 登入是否仍有效（過期就清掉，避免拿失效 cookie 去請求）

        At start-up, check that the remembered Bilibili login is still valid (an expired one is cleared so
        we don't send requests with a dead cookie).
        """
        if not bilibili.COOKIE_FILE.exists():
            return
        try:
            acc = await bilibili.fetch_account()
        except bilibili.BiliError as exc:
            log.warning("暫時無法確認 Bilibili 登入狀態：%s", exc)
            return
        if acc is None:
            log.info("Bilibili 登入已過期，已清除")
            bilibili.logout()
        else:
            bilibili.remember_account(acc)
            log.info("Bilibili 已登入：%s（%s）", acc["name"], acc["vip_label"])
        self._notify_all()

    async def bili_login_flow(self, emit: Emit) -> None:
        """QR 掃碼登入：產生 QR → 輪詢掃碼狀態 → 存 cookie → 記住帳號，進度用 emit 回報給發起的那個瀏覽器

        QR-code login: generate a QR -> poll the scan status -> save the cookies -> remember the account.
        Progress is reported through ``emit`` to the browser that started the flow.
        """
        try:
            url, key = await bilibili.qr_generate()
            await emit({"type": "bili_qr", "img": bilibili.qr_image(url), "ttl": bilibili.QR_LIFETIME})
            deadline = time.monotonic() + bilibili.QR_LIFETIME + 5
            last = None
            while time.monotonic() < deadline:
                await asyncio.sleep(2)
                code, cookies = await bilibili.qr_poll(key)
                if code == bilibili.CODE_OK and cookies:
                    bilibili.save_cookies(cookies)
                    acc = await bilibili.fetch_account()
                    bilibili.remember_account(acc)
                    sources.clear_search_cache()
                    log.info("Bilibili 登入成功：%s", acc["name"] if acc else "?")
                    self._notify_all()
                    await emit({"type": "bili_status", "status": "ok", "account": acc})
                    return
                if code == bilibili.CODE_EXPIRED:
                    break
                if code != last:
                    last = code
                    status = "scanned" if code == bilibili.CODE_SCANNED else "waiting"
                    await emit({"type": "bili_status", "status": status})
            await emit({"type": "bili_status", "status": "expired"})
        except bilibili.BiliError as exc:
            await emit({"type": "bili_status", "status": "error", "text": str(exc)})
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("Bilibili 登入流程失敗")
            await emit({"type": "bili_status", "status": "error", "text": f"登入失敗：{str(exc)[:120]}"})
