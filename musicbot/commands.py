"""Discord 斜線指令（只註冊在主機器人；實際工作交給 Hub 依使用者所在的語音頻道派給對應的播放器）

Discord slash commands. They are registered on the main bot only; the real work is handed to the Hub,
which picks the right player according to the voice channel the user is in.

Everything lives inside ``register(hub)`` so the commands can close over ``hub`` without globals:
  [shared helpers] -> /help, /unverify -> /join, /play (+ context menu) -> /skip /pause /resume /stop /loop
  -> /quality, /queue, /nowplaying, /players
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands

from .config import QUALITY_CHOICES
from .hub import Hub
from .player import LOOP_LABEL, LOOP_MODES

log = logging.getLogger("musicbot")

# 邀請連結要的權限：View Channel + Send Messages + Embed Links + Connect + Speak
# Permissions requested by the invite link: View Channel + Send Messages + Embed Links + Connect + Speak
INVITE_PERMISSIONS = 1024 + 2048 + 16384 + 1048576 + 2097152
WHEN_LABEL = {"end": "加到最後", "next": "下一首播放", "now": "立刻播放"}   # /play 的"加到哪裡"選項 / the "where to add" choices of /play


def invite_url(client_id: int, with_commands: bool = True) -> str:
    """產生把機器人邀請進伺服器的連結，分身不需要斜線指令，所以可以不帶 applications.commands

    Build the link that invites a bot to a server. Clones don't need slash commands, so they can skip the
    ``applications.commands`` scope (``with_commands=False``).
    """
    scope = "bot%20applications.commands" if with_commands else "bot"
    return f"https://discord.com/oauth2/authorize?client_id={client_id}&scope={scope}&permissions={INVITE_PERMISSIONS}"


def register(hub: Hub) -> None:
    """把所有斜線指令註冊到主機器人的指令樹

    Register every slash command on the main bot's command tree.
    """
    tree = hub.primary.tree

    # ============================================================
    # 共用小工具 / Shared helpers
    # ============================================================
    async def say(interaction: discord.Interaction, text: str | None = None, *, embed=None, ephemeral=False) -> None:
        """回覆互動：已回應過就用 followup，否則第一次回應

        Reply to an interaction: use a followup if it was already answered, otherwise the first response.
        ``ephemeral=True`` makes the reply visible only to the user who ran the command.
        """
        if interaction.response.is_done():
            await interaction.followup.send(content=text, embed=embed, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(content=text, embed=embed, ephemeral=ephemeral)

    def member_voice(interaction: discord.Interaction):
        """使用者目前所在的語音頻道；不在語音頻道就回傳 None / The voice channel the user is in, or None."""
        m = interaction.user
        return m.voice.channel if isinstance(m, discord.Member) and m.voice and m.voice.channel else None

    async def in_guild(interaction: discord.Interaction) -> bool:
        """指令必須在伺服器內使用（私訊不行） / Commands must be used inside a server (not in DMs)."""
        if interaction.guild:
            return True
        await say(interaction, "只能在伺服器中使用。", ephemeral=True)
        return False

    async def my_player(interaction: discord.Interaction):
        """使用者所在頻道裡的播放器 (worker, guild)；沒有就回覆提示並回傳 None

        The player that serves the user's current channel as ``(worker, guild)``; replies with a hint
        and returns None when there isn't one.
        """
        if not await in_guild(interaction):
            return None
        if member_voice(interaction) is None:
            await say(interaction, "請先加入一個語音頻道。", ephemeral=True)
            return None
        w, g, _ = hub.pick_for_user(interaction.guild.id, interaction.user.id, create=False)
        if w is None:
            await say(interaction, "你所在的語音頻道目前沒有播放器。用 `/play` 或 `/join` 叫機器人進來。", ephemeral=True)
            return None
        return w, g

    async def play_impl(interaction: discord.Interaction, query: str, when: str) -> None:
        """/play 與右鍵選單共用的實作：挑播放器 → 解析 → 加入待播

        Shared by /play and the context menu: pick a player -> resolve the query -> enqueue it.
        """
        if not await in_guild(interaction):
            return
        member = interaction.user
        vch = member_voice(interaction)
        if vch is None:
            return await say(interaction, "請先加入一個語音頻道。", ephemeral=True)
        w, g, _ = hub.pick_for_user(interaction.guild.id, member.id, create=True)
        if w is None:
            return await say(interaction, hub.all_busy_message(interaction.guild.id), ephemeral=True)
        await interaction.response.defer()   # 解析網址可能要幾秒，先告訴 Discord"處理中"/ resolving can take seconds; tell Discord we're working on it
        w.state(g.id).text_channel_id = interaction.channel_id
        tracks, info = await w.enqueue(g, query, member.display_name, g.get_channel(vch.id), when,
                                       member.display_avatar.with_size(64).url)
        if not tracks:
            return await say(interaction, f"{info}")
        names = "、".join(t.title or t.url for t in tracks[:3]) + (f" 等 {len(tracks)} 首" if len(tracks) > 3 else "")
        await say(interaction, f"已{WHEN_LABEL[when]}：{names}" + (f"\n{info}" if info else ""))

    # ============================================================
    # 說明與身分 / Help and identity
    # ============================================================
    @tree.command(name="help", description="說明，並取得你專屬的網頁控制看板連結")
    async def help_cmd(interaction: discord.Interaction) -> None:
        """顯示說明；依看板存取模式附上對應的連結（只有本人看得到）

        Show help; depending on the dashboard access mode it also includes the matching link (visible only to the caller).
        """
        embed = discord.Embed(title="音樂機器人", color=0x5F7EAE)
        embed.description = "預設搜尋 **Bilibili**，自動選最高音質。貼網址、BV 號、整段分享文字都能自動辨識。"
        embed.add_field(
            name="指令",
            value=(
                "`/play` 貼網址（Bilibili／YouTube／Spotify）、BV 號或關鍵字（可選：下一首／立刻播放）\n"
                "`/join` 讓機器人進入你的語音頻道\n"
                "`/skip` `/pause` `/resume` `/stop` `/loop`\n"
                "`/queue` `/nowplaying` `/quality` `/players`\n"
                "對任何訊息按右鍵 → 應用程式 → **加入播放佇列**"
            ),
            inline=False,
        )
        if interaction.guild:
            gid, user = interaction.guild.id, interaction.user
            if hub.mode == "verify":
                # 驗證模式：給專屬連結（點一下就綁定身分並記住瀏覽器）
                # verify mode: a personal link (one click binds the identity and remembers the browser)
                url, mine = hub.guild_url(gid), hub.link_for(gid, user.id, user.display_name)
                embed.add_field(
                    name="網頁控制看板（你專屬的連結）",
                    value=(
                        f"[**點此開啟看板**]({mine})\n"
                        "點一下就好：自動確認你的 Discord 身分、看板顯示你的暱稱，並記住這個瀏覽器，"
                        "下次直接開 " + url + " 就能進來，不用再點連結。可以控制所有頻道。\n"
                        "換新裝置時，在那個裝置上再輸入一次 `/help` 點連結就好。"
                        "連結 12 小時有效、綁定你的身分，請勿轉貼（朋友自己輸入 `/help` 就有他的）。"
                    ),
                    inline=False,
                )
            elif hub.open_access:
                # 開放模式：所有人共用同一個網址；擁有者另外有專用連結
                # open mode: everyone shares one URL; the owner additionally gets a personal link
                url = hub.guild_url(gid)
                embed.add_field(
                    name="網頁控制看板",
                    value=(
                        f"[**點此開啟看板**]({url})\n{url}\n"
                        "所有人用同一個網址，不需要各自的連結。在看板上選頻道、貼網址加歌、拖曳排序、調進度與音質，"
                        "可以控制這個伺服器所有頻道的播放。"
                    ),
                    inline=False,
                )
                if user.id in hub.owner_ids:
                    owner_url = hub.link_for(gid, user.id, user.display_name)
                    embed.add_field(
                        name="擁有者專用連結（可更換 Bilibili 帳號）",
                        value=f"[點此開啟]({owner_url})\n綁定你的身分、12 小時有效，請勿轉貼。在執行機器人的那台電腦上開 localhost 也有同樣權限。",
                        inline=False,
                    )
            else:
                # 語音模式：連結綁定身分，而且人要在語音頻道裡才能控制
                # voice mode: the link is bound to the identity, and you must be in a voice channel to control
                url = hub.link_for(gid, user.id, user.display_name)
                embed.add_field(
                    name="網頁控制看板（你專屬的連結）",
                    value=(
                        f"[**點此開啟看板**]({url})\n"
                        "拖曳排序、拖到右側刪除、調進度與音質。**只有人在語音頻道裡才能控制**；"
                        "連結 12 小時有效、綁定你的身分，請不要轉貼給別人（朋友自己輸入 `/help` 就有他的）。"
                    ),
                    inline=False,
                )
        await say(interaction, embed=embed, ephemeral=True)

    @tree.command(name="unverify", description="撤銷已記住的看板裝置（不指定對象就是撤銷你自己的所有裝置）")
    @app_commands.describe(user="（僅機器人擁有者）撤銷別人的裝置")
    async def unverify(interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        """撤銷已記住的裝置；撤銷別人需要是機器人擁有者

        Revoke remembered dashboard devices; revoking someone else's requires being the bot owner.
        """
        target = user or interaction.user
        if target.id != interaction.user.id and interaction.user.id not in hub.owner_ids:
            return await say(interaction, "只有機器人的擁有者可以撤銷別人的裝置。", ephemeral=True)
        n = hub.revoke_user(target.id)
        who = "你" if target.id == interaction.user.id else f"**{target.display_name}**"
        await say(interaction, f"已撤銷{who}的 {n} 個裝置。" if n else f"{who}沒有已記住的裝置。", ephemeral=True)

    # ============================================================
    # 加入語音與播放 / Joining voice and playing
    # ============================================================
    @tree.command(name="join", description="讓機器人加入你所在的語音頻道")
    async def join(interaction: discord.Interaction) -> None:
        """叫一個機器人（主機器人或閒置的分身）進你所在的語音頻道

        Bring a bot (the main one or an idle clone) into the voice channel you are in.
        """
        if not await in_guild(interaction):
            return
        vch = member_voice(interaction)
        if vch is None:
            return await say(interaction, "請先加入一個語音頻道。", ephemeral=True)
        w, g, _ = hub.pick_for_user(interaction.guild.id, interaction.user.id, create=True)
        if w is None:
            return await say(interaction, hub.all_busy_message(interaction.guild.id), ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        try:
            await w.ensure_voice(g, g.get_channel(vch.id))
            w.state(g.id).text_channel_id = interaction.channel_id
            await w.ensure_playing(g)
        finally:
            w.release(g.id)   # 不論成功失敗都解除預約 / release the reservation whether it worked or not
        hub.notify(g.id)
        await say(interaction, f"**{w.label}** 已加入 **{vch.name}**", ephemeral=True)

    @tree.command(name="play", description="播放：貼網址、BV 號，或輸入關鍵字（自動辨識）")
    @app_commands.describe(
        query="Bilibili／YouTube 等網址、BV 號，或關鍵字（關鍵字預設搜尋 Bilibili；YouTube 搜尋請加 yt: 前綴）",
        when="加到哪裡（預設：加到最後）",
    )
    @app_commands.choices(when=[app_commands.Choice(name=v, value=k) for k, v in WHEN_LABEL.items()])
    async def play(interaction: discord.Interaction, query: str, when: str = "end") -> None:
        """加歌，實作在 play_impl / Queue a song. The implementation lives in play_impl."""
        await play_impl(interaction, query, when)

    @tree.context_menu(name="加入播放佇列")
    async def add_from_message(interaction: discord.Interaction, message: discord.Message) -> None:
        """對任何含連結的訊息按右鍵就能加歌（朋友貼了 Bilibili 連結，一鍵加入）

        Right-click any message that contains a link to queue it (a friend pasted a Bilibili link? one click adds it).
        """
        text = " ".join([message.content, *[e.url for e in message.embeds if e.url]]).strip()
        if not text:
            return await say(interaction, "這則訊息裡沒有可以播放的連結。", ephemeral=True)
        await play_impl(interaction, text, "end")

    # ============================================================
    # 播放控制 / Playback controls
    # ============================================================
    @tree.command(name="skip", description="跳過目前這首")
    async def skip(interaction: discord.Interaction) -> None:
        """跳過你所在頻道正在播的歌 / Skip the song playing in your channel."""
        mine = await my_player(interaction)
        if mine:
            await say(interaction, "已跳過" if mine[0].skip(mine[1]) else "目前沒有在播放。", ephemeral=False)

    @tree.command(name="pause", description="暫停")
    async def pause(interaction: discord.Interaction) -> None:
        """暫停播放 / Pause playback."""
        mine = await my_player(interaction)
        if mine:
            ok = mine[0].pause(mine[1])
            await say(interaction, "已暫停" if ok else "目前沒有在播放。", ephemeral=not ok)

    @tree.command(name="resume", description="繼續播放")
    async def resume(interaction: discord.Interaction) -> None:
        """繼續播放 / Resume playback."""
        mine = await my_player(interaction)
        if mine:
            ok = mine[0].resume(mine[1])
            await say(interaction, "已繼續" if ok else "目前沒有暫停中的音樂。", ephemeral=not ok)

    @tree.command(name="stop", description="停止播放、清空佇列並離開語音頻道")
    async def stop(interaction: discord.Interaction) -> None:
        """停止、清空待播並離開語音頻道（也會讓分身被釋放） / Stop, clear the queue and leave the voice channel (this also frees a clone)."""
        mine = await my_player(interaction)
        if mine:
            await mine[0].stop(mine[1])
            await say(interaction, "已停止並離開")

    @tree.command(name="loop", description="設定循環模式")
    @app_commands.choices(mode=[app_commands.Choice(name=LOOP_LABEL[m], value=m) for m in LOOP_MODES])
    async def loop_cmd(interaction: discord.Interaction, mode: str) -> None:
        """設定循環模式：關閉／單曲／列表 / Set the loop mode: off / single / queue."""
        mine = await my_player(interaction)
        if mine:
            mine[0].set_loop(mine[1].id, mode)
            await say(interaction, f"循環模式：**{LOOP_LABEL[mode]}**")

    @tree.command(name="quality", description="設定這個伺服器的音質（Opus 位元率）；正在播放的歌會從原位置重新開始")
    @app_commands.describe(kbps="位元率，數字越大越接近來源音質、也越耗頻寬")
    @app_commands.choices(kbps=[app_commands.Choice(name=f"{k} kbps", value=k) for k in QUALITY_CHOICES])
    async def quality_cmd(interaction: discord.Interaction, kbps: int) -> None:
        """設定這個伺服器的音質（會存起來） / Set this server's audio quality (it is saved)."""
        if not await in_guild(interaction):
            return
        if member_voice(interaction) is None:
            return await say(interaction, "請先加入語音頻道才能調整音質。", ephemeral=True)
        hub.set_quality(interaction.guild.id, kbps)
        await say(interaction, f"這個伺服器的音質已設為 **Opus {kbps} kbps**")

    # ============================================================
    # 查詢 / Information
    # ============================================================
    @tree.command(name="queue", description="顯示你所在頻道的待播清單")
    async def queue_cmd(interaction: discord.Interaction) -> None:
        """列出正在播放與前 10 首待播 / List the current song and the first 10 queued songs."""
        mine = await my_player(interaction)
        if not mine:
            return
        st = mine[0].state(mine[1].id)
        lines = []
        if st.current:
            lines.append(f"**正在播放**：{st.current.title or st.current.url}")
        for i, t in enumerate(list(st.queue)[:10], 1):
            lines.append(f"{i}. {t.title or t.url}（{t.requester}）")
        if len(st.queue) > 10:
            lines.append(f"…還有 {len(st.queue) - 10} 首")
        lines.append(f"循環：{LOOP_LABEL[st.loop]}")
        await say(interaction, "\n".join(lines))

    @tree.command(name="nowplaying", description="目前播放的曲目與音質")
    async def nowplaying(interaction: discord.Interaction) -> None:
        """顯示目前曲目、來源音質與實際傳送的位元率 / Show the current song, source quality and the bitrate actually sent."""
        mine = await my_player(interaction)
        if not mine:
            return
        st = mine[0].state(mine[1].id)
        if not st.current or not st.stream:
            return await say(interaction, "目前沒有在播放。", ephemeral=True)
        s = st.stream
        await say(
            interaction,
            f"**{s.title}**\n來源音質：`{s.quality}` → 傳送：`Opus {st.bitrate_kbps}kbps`\n點歌者：{st.current.requester}",
        )

    @tree.command(name="players", description="看這個伺服器所有播放器（含分身）的狀態，以及分身的邀請連結")
    async def players_cmd(interaction: discord.Interaction) -> None:
        """列出所有機器人帳號（主機器人 + 分身）在這個伺服器的狀態

        List the state of every bot account (main + clones) in this server.
        """
        if not await in_guild(interaction):
            return
        gid = interaction.guild.id
        lines = []
        for w in hub.workers:
            g = w.get_guild(gid)
            role = "主機器人" if w.is_primary else "分身"
            if g is None:
                lines.append(f"**{w.label}**（{role}）：還沒加入這個伺服器 → [邀請]({invite_url(w.user.id, w.is_primary)})")
                continue
            st, vc = w.state(gid), g.voice_client
            if vc:
                now = f"在「{vc.channel.name}」" + (f"播放：{st.current.title}" if st.current else "（待命）")
            else:
                now = "閒置，可接手新的頻道"
            lines.append(f"**{w.label}**（{role}）：{now}")
        if len(hub.workers) == 1:
            lines.append("\n目前只有 1 個機器人，同一時間只能在 1 個語音頻道播放。要同時多頻道播放請設定分身（見 README）。")
        text = "\n".join(lines)
        if len(text) > 1900:     # 分身沒有數量上限，訊息可能超過 Discord 的 2000 字元 / clones are unlimited, so the message could exceed Discord's 2000-character cap
            text = text[:1900].rsplit("\n", 1)[0] + "\n…（太長，只顯示前面的）"
        await say(interaction, text, ephemeral=True)
