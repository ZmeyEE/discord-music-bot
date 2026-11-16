"""各種檔案位置

用 PyInstaller 打包成 exe 時（sys.frozen），使用者資料放在 exe 旁邊，
唯讀的內建資源（web/ 前端）在 PyInstaller 解壓縮的暫存資料夾（sys._MEIPASS）

Where files live.

When the bot is frozen into an exe with PyInstaller (``sys.frozen``), user data sits
next to the exe, while read-only bundled resources (the ``web/`` front-end) are in
PyInstaller's temporary extraction folder (``sys._MEIPASS``). When running from
source, both are simply the project folder.
"""
from __future__ import annotations

import sys
from pathlib import Path

# ============================================================
# 執行環境 / Runtime environment
# ============================================================
FROZEN = bool(getattr(sys, "frozen", False))  # 是否為打包後的 exe / True when running as a PyInstaller exe

# 使用者資料（.env、cookies.txt、settings.json、logs/）所在資料夾
# Folder holding user data (.env, cookies.txt, settings.json, logs/)
BASE = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent.parent
# 唯讀內建資源所在資料夾 / Folder holding read-only bundled resources
RES = Path(getattr(sys, "_MEIPASS", BASE))

# ============================================================
# 檔案與資料夾 / Files and folders
# ============================================================
WEB_DIR = RES / "web"                    # 網頁看板前端 / dashboard front-end
LOG_DIR = BASE / "logs"                  # 紀錄檔 / log files
ENV_FILE = BASE / ".env"                 # 機密設定（Token 等）/ secrets such as bot tokens
COOKIE_FILE = BASE / "cookies.txt"       # Bilibili 登入 cookie（Netscape 格式，yt-dlp 讀取）/ Bilibili login cookie (Netscape format, read by yt-dlp)
SETTINGS_FILE = BASE / "settings.json"   # 音質、Bilibili 帳號顯示資訊、後台簽章金鑰 / audio quality, Bilibili account info, dashboard signing secret
MEMBERS_FILE = BASE / "members.json"     # 驗證過的 Discord 成員與他們的裝置（只存在執行機器人的這台電腦）/ verified Discord members and their devices (stored only on the machine running the bot)
LIBRARY_FILE = BASE / "library.json"     # 每個人的歌單與資料夾（存在這台電腦）/ everyone's playlists and folders (stored on this machine)
SPOTIFY_FILE = BASE / "spotify_tokens.json"   # 各人連結 Spotify 後的憑證（存在這台電腦，不上傳）/ the tokens after each person links Spotify (stored on this machine, never uploaded)
