"""資訊與身分：/help /unverify /queue /nowplaying /players

Information and identity: /help /unverify /queue /nowplaying /players
"""
from __future__ import annotations

import discord
from discord import app_commands

from ..hub import Hub
from ..player import LOOP_LABEL
from .helpers import Helpers, invite_url


def register(tree: app_commands.CommandTree, hub: Hub, h: Helpers) -> None:
    """資訊與身分 / registered on the main bot's command tree"""
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
        await h.say(interaction, embed=embed, ephemeral=True)

    @tree.command(name="unverify", description="撤銷已記住的看板裝置（不指定對象就是撤銷你自己的所有裝置）")
    @app_commands.describe(user="（僅機器人擁有者）撤銷別人的裝置")
    async def unverify(interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        """撤銷已記住的裝置；撤銷別人需要是機器人擁有者

        Revoke remembered dashboard devices; revoking someone else's requires being the bot owner.
        """
        target = user or interaction.user
        if target.id != interaction.user.id and interaction.user.id not in hub.owner_ids:
            return await h.say(interaction, "只有機器人的擁有者可以撤銷別人的裝置。", ephemeral=True)
        n = hub.revoke_user(target.id)
        who = "你" if target.id == interaction.user.id else f"**{target.display_name}**"
        await h.say(interaction, f"已撤銷{who}的 {n} 個裝置。" if n else f"{who}沒有已記住的裝置。", ephemeral=True)

    @tree.command(name="queue", description="顯示你所在頻道的待播清單")
    async def queue_cmd(interaction: discord.Interaction) -> None:
        """列出正在播放與前 10 首待播 / List the current song and the first 10 queued songs."""
        mine = await h.my_player(interaction)
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
        await h.say(interaction, "\n".join(lines))

    @tree.command(name="nowplaying", description="目前播放的曲目與音質")
    async def nowplaying(interaction: discord.Interaction) -> None:
        """顯示目前曲目、來源音質與實際傳送的位元率 / Show the current song, source quality and the bitrate actually sent."""
        mine = await h.my_player(interaction)
        if not mine:
            return
        st = mine[0].state(mine[1].id)
        if not st.current or not st.stream:
            return await h.say(interaction, "目前沒有在播放。", ephemeral=True)
        s = st.stream
        await h.say(
            interaction,
            f"**{s.title}**\n來源音質：`{s.quality}` → 傳送：`Opus {st.bitrate_kbps}kbps`\n點歌者：{st.current.requester}",
        )

    @tree.command(name="players", description="看這個伺服器所有播放器（含分身）的狀態，以及分身的邀請連結")
    async def players_cmd(interaction: discord.Interaction) -> None:
        """列出所有機器人帳號（主機器人 + 分身）在這個伺服器的狀態

        List the state of every bot account (main + clones) in this server.
        """
        if not await h.in_guild(interaction):
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
        await h.say(interaction, text, ephemeral=True)
