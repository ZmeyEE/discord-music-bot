"""網頁後台

分兩層，方便"本地後台"與"遠端中繼站"共用同一套邏輯：
- DashboardCore：與傳輸方式無關，工作階段（一個瀏覽器分頁一個）、身分判斷、權限、操作分派、廣播
- Dashboard：本地的 aiohttp 伺服器（靜態頁面 + WebSocket），把瀏覽器連線接到 DashboardCore
  遠端中繼站（relay.py / relay_client.py）也是把瀏覽器連線接到同一個 DashboardCore

存取控制（見 Hub 與 README"誰能做什麼"）：
- 從執行機器人的這台電腦直接開 http://localhost:埠 = 本地主人，不需要憑證
- 驗證模式：點 /help 給的專屬連結進來（自動綁定 Discord 身分並記住這個瀏覽器），沒有連結什麼都不能做
- 語音模式：必須帶 /help 簽出的憑證，而且人要在語音頻道裡才能控制
- 只接受同源的 WebSocket，其他網站無法偷連你的後台

The web dashboard.

Two layers, so the "local dashboard" and the "remote relay" can share the same logic:
- DashboardCore: independent of the transport. Sessions (one per browser tab), identity checks, permissions,
  action dispatch and broadcasting.
- Dashboard: the local aiohttp server (static page + WebSocket) that plugs browser connections into
  DashboardCore. The remote relay (relay.py / relay_client.py) plugs browsers into the same DashboardCore.

Access control (see Hub and the README section "誰能做什麼 / who can do what"):
- Opening http://localhost:<port> on the machine running the bot = local owner, no token needed.
- verify mode (default; the only way in is a personal link, since 2.0 there is no "open" mode): come in through the personal link from /help (binds the Discord identity and remembers the
  browser); without it nothing can be done.
- voice mode: a token signed by /help is required, and you must be in a voice channel to control playback.
- Only same-origin WebSockets are accepted, so other websites can't connect to your dashboard behind your back.

Browser <-> server messages (JSON) / 瀏覽器與伺服器之間的訊息:
  server -> browser:  state | toast | error | verified | revoked | (Bilibili login progress messages)
  browser -> server:  select | bili_login_start | bili_login_cancel | <any action handled by Hub.handle_action>

檔案 / files:
  session.py  一個瀏覽器連線 / one browser connection
  core.py     核心 / core
  server.py   本機網頁伺服器 / local web server
"""
from .core import DashboardCore
from .server import Dashboard
from .session import Emit, Session, clean_name

__all__ = ["Dashboard", "DashboardCore", "Session", "Emit", "clean_name"]
