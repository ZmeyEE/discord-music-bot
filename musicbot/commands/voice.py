"""加入語音與加歌：/join /play 和右鍵選單

Joining voice and adding songs: /join, /play and the context menu
"""
from __future__ import annotations

import discord
from discord import app_commands

from ..hub import Hub
from .helpers import WHEN_LABEL, Helpers


def register(tree: app_commands.CommandTree, hub: Hub, h: Helpers) -> None:
    """加入語音與加歌 / registered on the main bot's command tree"""
    @tree.command(name="join", description="讓機器人加入你所在的語音頻道")
    async def join(interaction: discord.Interaction) -> None:
        """叫一個機器人（主機器人或閒置的分身）進你所在的語音頻道

        Bring a bot (the main one or an idle clone) into the voice channel you are in.
        """
        if not await h.in_guild(interaction):
            return
        vch = h.member_voice(interaction)
        if vch is None:
            return await h.say(interaction, "請先加入一個語音頻道。", ephemeral=True)
        w, g, _ = hub.pick_for_user(interaction.guild.id, interaction.user.id, create=True)
        if w is None:
            return await h.say(interaction, hub.all_busy_message(interaction.guild.id), ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        try:
            await w.ensure_voice(g, g.get_channel(vch.id))
            w.state(g.id).text_channel_id = interaction.channel_id
            await w.ensure_playing(g)
        finally:
            w.release(g.id)   # 不論成功失敗都解除預約 / release the reservation whether it worked or not
        hub.notify(g.id)
        await h.say(interaction, f"**{w.label}** 已加入 **{vch.name}**", ephemeral=True)

    @tree.command(name="play", description="播放：貼網址、BV 號，或輸入關鍵字（自動辨識）")
    @app_commands.describe(
        query="Bilibili／YouTube 等網址、BV 號，或關鍵字（關鍵字預設搜尋 Bilibili；YouTube 搜尋請加 yt: 前綴）",
        when="加到哪裡（預設：加到最後）",
    )
    @app_commands.choices(when=[app_commands.Choice(name=v, value=k) for k, v in WHEN_LABEL.items()])
    async def play(interaction: discord.Interaction, query: str, when: str = "end") -> None:
        """加歌，實作在 play_impl / Queue a song. The implementation lives in play_impl."""
        await h.play_impl(interaction, query, when)

    @tree.context_menu(name="加入播放佇列")
    async def add_from_message(interaction: discord.Interaction, message: discord.Message) -> None:
        """對任何含連結的訊息按右鍵就能加歌（朋友貼了 Bilibili 連結，一鍵加入）

        Right-click any message that contains a link to queue it (a friend pasted a Bilibili link? one click adds it).
        """
        text = " ".join([message.content, *[e.url for e in message.embeds if e.url]]).strip()
        if not text:
            return await h.say(interaction, "這則訊息裡沒有可以播放的連結。", ephemeral=True)
        await h.play_impl(interaction, text, "end")
