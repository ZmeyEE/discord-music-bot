"""Discord 斜線指令（只註冊在主機器人；實際工作交給 Hub 依使用者所在的語音頻道派給對應的播放器）

Discord slash commands, registered on the main bot only; the real work is handed to the Hub, which picks the right player by the voice channel the user is in.
"""
from ..hub import Hub
from . import controls, info, voice
from .helpers import WHEN_LABEL, Helpers, invite_url


def register(hub: Hub) -> None:
    """把所有斜線指令註冊到主機器人的指令樹

    Register every slash command on the main bot's command tree.
    """
    tree = hub.primary.tree
    h = Helpers(hub)
    info.register(tree, hub, h)       # /help /unverify /queue /nowplaying /players
    voice.register(tree, hub, h)      # /join /play、右鍵選單 / context menu
    controls.register(tree, hub, h)   # /skip /pause /resume /stop /loop /quality


__all__ = ["register", "invite_url", "WHEN_LABEL", "Helpers"]
