"""播放控制：/skip /pause /resume /stop /loop /quality

Playback controls: /skip /pause /resume /stop /loop /quality
"""
from __future__ import annotations

import discord
from discord import app_commands

from .. import params
from ..hub import Hub
from ..player import LOOP_LABEL, LOOP_MODES
from .helpers import Helpers


def register(tree: app_commands.CommandTree, hub: Hub, h: Helpers) -> None:
    """播放控制 / registered on the main bot's command tree"""
    @tree.command(name="skip", description="跳過目前這首")
    async def skip(interaction: discord.Interaction) -> None:
        """跳過你所在頻道正在播的歌 / Skip the song playing in your channel."""
        mine = await h.my_player(interaction)
        if mine:
            await h.say(interaction, "已跳過" if mine[0].skip(mine[1]) else "目前沒有在播放。", ephemeral=False)

    @tree.command(name="pause", description="暫停")
    async def pause(interaction: discord.Interaction) -> None:
        """暫停播放 / Pause playback."""
        mine = await h.my_player(interaction)
        if mine:
            ok = mine[0].pause(mine[1])
            await h.say(interaction, "已暫停" if ok else "目前沒有在播放。", ephemeral=not ok)

    @tree.command(name="resume", description="繼續播放")
    async def resume(interaction: discord.Interaction) -> None:
        """繼續播放 / Resume playback."""
        mine = await h.my_player(interaction)
        if mine:
            ok = mine[0].resume(mine[1])
            await h.say(interaction, "已繼續" if ok else "目前沒有暫停中的音樂。", ephemeral=not ok)

    @tree.command(name="stop", description="停止播放、清空佇列並離開語音頻道")
    async def stop(interaction: discord.Interaction) -> None:
        """停止、清空待播並離開語音頻道（也會讓分身被釋放） / Stop, clear the queue and leave the voice channel (this also frees a clone)."""
        mine = await h.my_player(interaction)
        if mine:
            await mine[0].stop(mine[1])
            await h.say(interaction, "已停止並離開")

    @tree.command(name="loop", description="設定循環模式")
    @app_commands.choices(mode=[app_commands.Choice(name=LOOP_LABEL[m], value=m) for m in LOOP_MODES])
    async def loop_cmd(interaction: discord.Interaction, mode: str) -> None:
        """設定循環模式：關閉／單曲／列表 / Set the loop mode: off / single / queue."""
        mine = await h.my_player(interaction)
        if mine:
            mine[0].set_loop(mine[1].id, mode)
            await h.say(interaction, f"循環模式：**{LOOP_LABEL[mode]}**")

    @tree.command(name="quality", description="設定這個伺服器的音質（Opus 位元率）；正在播放的歌會從原位置重新開始")
    @app_commands.describe(kbps="位元率，數字越大越接近來源音質、也越耗頻寬")
    @app_commands.choices(kbps=[app_commands.Choice(name=f"{k} kbps", value=k) for k in params.QUALITY_CHOICES])
    async def quality_cmd(interaction: discord.Interaction, kbps: int) -> None:
        """設定這個伺服器的音質（會存起來） / Set this server's audio quality (it is saved)."""
        if not await h.in_guild(interaction):
            return
        if h.member_voice(interaction) is None:
            return await h.say(interaction, "請先加入語音頻道才能調整音質。", ephemeral=True)
        hub.set_quality(interaction.guild.id, kbps)
        await h.say(interaction, f"這個伺服器的音質已設為 **Opus {kbps} kbps**")
