"""斜線指令共用的小工具：回覆、使用者所在頻道、挑播放器、/play 的實作

Helpers shared by the slash commands: replying, the user's voice channel, picking a player, the /play implementation
"""
from __future__ import annotations

import discord

from .. import params
from ..hub import Hub

WHEN_LABEL = {"end": "加到最後", "next": "下一首播放", "now": "立刻播放"}   # /play 的"加到哪裡"選項 / the "where to add" choices of /play


def invite_url(client_id: int, with_commands: bool = True) -> str:
    """產生把機器人邀請進伺服器的連結，分身不需要斜線指令，所以可以不帶 applications.commands

    Build the link that invites a bot to a server. Clones don't need slash commands, so they can skip the
    ``applications.commands`` scope (``with_commands=False``).
    """
    scope = "bot%20applications.commands" if with_commands else "bot"
    return f"https://discord.com/oauth2/authorize?client_id={client_id}&scope={scope}&permissions={params.INVITE_PERMISSIONS}"


class Helpers:
    """所有指令共用，持有 Hub / Shared by every command; holds the Hub."""

    def __init__(self, hub: Hub) -> None:
        self.hub = hub

    async def say(self, interaction: discord.Interaction, text: str | None = None, *, embed=None, ephemeral=False) -> None:
        """回覆互動：已回應過就用 followup，否則第一次回應

        Reply to an interaction: use a followup if it was already answered, otherwise the first response.
        ``ephemeral=True`` makes the reply visible only to the user who ran the command.
        """
        if interaction.response.is_done():
            await interaction.followup.send(content=text, embed=embed, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(content=text, embed=embed, ephemeral=ephemeral)

    def member_voice(self, interaction: discord.Interaction):
        """使用者目前所在的語音頻道；不在語音頻道就回傳 None / The voice channel the user is in, or None."""
        m = interaction.user
        return m.voice.channel if isinstance(m, discord.Member) and m.voice and m.voice.channel else None

    async def in_guild(self, interaction: discord.Interaction) -> bool:
        """指令必須在伺服器內使用（私訊不行） / Commands must be used inside a server (not in DMs)."""
        if interaction.guild:
            return True
        await self.say(interaction, "只能在伺服器中使用。", ephemeral=True)
        return False

    async def my_player(self, interaction: discord.Interaction):
        """使用者所在頻道裡的播放器 (worker, guild)；沒有就回覆提示並回傳 None

        The player that serves the user's current channel as ``(worker, guild)``; replies with a hint
        and returns None when there isn't one.
        """
        if not await self.in_guild(interaction):
            return None
        if self.member_voice(interaction) is None:
            await self.say(interaction, "請先加入一個語音頻道。", ephemeral=True)
            return None
        w, g, _ = self.hub.pick_for_user(interaction.guild.id, interaction.user.id, create=False)
        if w is None:
            await self.say(interaction, "你所在的語音頻道目前沒有播放器。用 `/play` 或 `/join` 叫機器人進來。", ephemeral=True)
            return None
        return w, g

    async def play_impl(self, interaction: discord.Interaction, query: str, when: str) -> None:
        """/play 與右鍵選單共用的實作：挑播放器 → 解析 → 加入待播

        Shared by /play and the context menu: pick a player -> resolve the query -> enqueue it.
        """
        if not await self.in_guild(interaction):
            return
        member = interaction.user
        vch = self.member_voice(interaction)
        if vch is None:
            return await self.say(interaction, "請先加入一個語音頻道。", ephemeral=True)
        w, g, _ = self.hub.pick_for_user(interaction.guild.id, member.id, create=True)
        if w is None:
            return await self.say(interaction, self.hub.all_busy_message(interaction.guild.id), ephemeral=True)
        await interaction.response.defer()   # 解析網址可能要幾秒，先告訴 Discord"處理中"/ resolving can take seconds; tell Discord we're working on it
        w.state(g.id).text_channel_id = interaction.channel_id
        tracks, info = await w.enqueue(g, query, member.display_name, g.get_channel(vch.id), when,
                                       member.display_avatar.with_size(64).url)
        if not tracks:
            return await self.say(interaction, f"{info}")
        names = "、".join(t.title or t.url for t in tracks[:3]) + (f" 等 {len(tracks)} 首" if len(tracks) > 3 else "")
        await self.say(interaction, f"已{WHEN_LABEL[when]}：{names}" + (f"\n{info}" if info else ""))
