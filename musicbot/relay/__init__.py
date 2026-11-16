"""中繼站（控制台節點）：給"放歌在家裡、看板放在 VPS／樹莓派"的架構

    朋友的瀏覽器 ──▶ 中繼站（有公網 IP 的 VPS／樹莓派）◀── 家裡的機器人（主動連出來）

為什麼：家裡的電腦在路由器後面，朋友連不進來；而放歌必須留在家裡（住宅 IP 才能正常搜尋 Bilibili／YouTube，
也不需要買好的主機），所以讓家裡的機器人"主動連出"到中繼站，中繼站只負責把瀏覽器與機器人之間的訊息互相轉送

這個檔案只依賴 aiohttp：**不需要 discord.py、yt-dlp、ffmpeg**，樹莓派或最便宜的 VPS 就能跑
所有權限判斷與資料都仍在家裡的機器人那邊；中繼站不保存任何東西、也看不懂訊息內容

執行：  python -m musicbot.relay        （需要環境變數／.env 的 RELAY_KEY）

Relay (control-panel node): for the setup "play music at home, host the dashboard on a VPS / Raspberry Pi".

    friend's browser ──▶ relay (VPS / Pi with a public IP) ◀── bot at home (dials out)

Why: a home PC sits behind a router that friends can't reach, yet playback must stay at home (a residential
IP is what lets Bilibili / YouTube searches work normally, and you don't need a beefy server). So the bot at
home dials *out* to the relay, and the relay only forwards messages between browsers and the bot.

This file depends on aiohttp only: **no discord.py, yt-dlp or ffmpeg needed**, so a Raspberry Pi or the
cheapest VPS can run it. All permission checks and all data stay with the bot at home; the relay stores
nothing and cannot interpret the messages.

Run:  python -m musicbot.relay     (needs ``RELAY_KEY`` in the environment or .env)

Defences built in / 內建防護:
  * challenge-response handshake with RELAY_KEY (the key never travels over the network)
  * per-IP caps on simultaneous browsers, new connections per minute and unfinished handshakes
  * temporary lock-out after repeated failed handshakes
  * per-browser message rate limit, message size limit, same-origin check on WebSockets

檔案 / files:
  util.py     小工具 / helpers
  limits.py   連線與驗證上限 / connection and auth limits
  worker.py   播放端連線 / the home player
  browser.py  瀏覽器連線 / browsers
  server.py   組起來的 Relay / the assembled Relay
  cli.py      啟動入口（python -m musicbot.relay）/ entry point
"""
from .cli import main
from .server import Relay
from .util import Browser, client_ip, proof

__all__ = ["Relay", "Browser", "client_ip", "proof", "main"]
