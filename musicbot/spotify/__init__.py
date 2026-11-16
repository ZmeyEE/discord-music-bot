"""Spotify 帳號連結：讀自己的歌單，存進"我的歌單"

  client.py    Spotify 官方 API 的小客戶端（授權碼 + PKCE、續期、歌單與歌曲）
  accounts.py  每個人的憑證存檔（spotify_tokens.json）與授權暫存

網頁操作在 musicbot/hub/spotify.py，畫面在 web/js/spotify.js。限制見 client.py 的說明（開發模式 5 位使用者、擁有者要 Premium）
注意：沒有 Spotify Premium 的環境沒辦法對真的 Spotify 驗證，這裡的測試用假的 Spotify 回應

Spotify account link: read one's own playlists and save them into "My playlists".
  client.py    a small client of Spotify's official API (authorisation code + PKCE, refresh, playlists and songs)
  accounts.py  each person's tokens on disk (spotify_tokens.json) and the pending authorisations
The dashboard actions are musicbot/hub/spotify.py, the screen is web/js/spotify.js. The limits are explained in client.py
(Development Mode: 5 users, Premium owner). Note: without Spotify Premium this cannot be verified against the real Spotify, so the tests use fake Spotify answers.
"""
from .accounts import Accounts
from .client import SpotifyError

__all__ = ["Accounts", "SpotifyError"]
