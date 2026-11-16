"""播放引擎 / Playback engine
一個 Discord 機器人帳號 = 一個 PlayerBot，各功能拆在這個資料夾的檔案裡
One Discord bot account = one PlayerBot; each feature lives in its own file in this folder

  state.py     每個伺服器的播放狀態 / per-server state
  voice.py     語音頻道 / voice channel
  playback.py  播放 / playback
  recover.py   斷線救援 / outage recovery
  enqueue.py   加歌 / adding songs
  controls.py  播放控制 / controls
  snapshot.py  給網頁的狀態 / state for the dashboard
  bot.py       組起來的 PlayerBot / the assembled PlayerBot
"""
from .bot import PlayerBot
from .state import LOOP_LABEL, LOOP_MODES, GuildState, ffmpeg_stderr

__all__ = ["PlayerBot", "GuildState", "LOOP_MODES", "LOOP_LABEL", "ffmpeg_stderr"]
