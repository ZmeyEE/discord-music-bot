"""設定：.env、settings.json、音質、權杖、ffmpeg 位置

Configuration: .env, settings.json, audio quality, bot tokens and where ffmpeg lives.

Two layers of settings:
  1. ``.env``          -> environment variables, hand-edited, holds secrets (bot tokens...).
  2. ``settings.json`` -> values the bot itself changes at runtime (quality picks, Bilibili account
                          info, the dashboard signing secret). Read with get_setting / set_setting.
兩層設定：.env 由你手動編輯（含機密）；settings.json 由機器人執行時自己寫入（音質、帳號資訊、簽章金鑰）
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import shutil
from pathlib import Path

from .paths import BASE, ENV_FILE, SETTINGS_FILE
from . import params

log = logging.getLogger("musicbot")


_settings: dict = {}   # settings.json 的記憶體副本 / in-memory copy of settings.json


# ============================================================
# .env 讀取 / Reading .env
# ============================================================
def load_env() -> None:
    """讀取 .env（KEY=VALUE），不覆蓋已存在的環境變數

    Read ``.env`` (KEY=VALUE per line). Variables that already exist in the real environment
    win, so you can still override a value from the command line.
    """
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    params.apply_env()   # 參數檔在 .env 之前就載入了，這裡把 .env 裡的值補套進去 / params was imported before .env was read; apply the .env values now


def env_int(name: str, default: int) -> int:
    """讀取整數型環境變數；缺少或格式不對就用預設值

    Read an integer environment variable; fall back to ``default`` if missing or malformed.
    """
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# ============================================================
# 權杖與外部程式 / Tokens and external programs
# ============================================================
def discord_tokens() -> list[str]:
    """主機器人 DISCORD_TOKEN，加上分身 DISCORD_TOKEN_2、DISCORD_TOKEN_3 …（有幾個填幾個，沒有上限；
    也可以用 EXTRA_TOKENS 逗號分隔），撐不住時由卡頓偵測器（health.py）自動從最後加入的頻道開始逐個停止

    All bot tokens in order: the main ``DISCORD_TOKEN`` first, then clones ``DISCORD_TOKEN_2``,
    ``DISCORD_TOKEN_3`` ... (as many as you like, no upper limit). ``EXTRA_TOKENS`` (comma-separated)
    is accepted too. Duplicates and the .env.example placeholder are skipped. If the machine cannot keep
    up, the stutter detector (health.py) stops clones one by one, newest first.
    """
    numbered = sorted(
        ((int(m.group(1)), v) for k, v in os.environ.items() if (m := re.fullmatch(r"DISCORD_TOKEN_(\d+)", k))),
    )
    raw = [os.environ.get("DISCORD_TOKEN", ""), *(v for _, v in numbered)]
    raw += os.environ.get("EXTRA_TOKENS", "").split(",")
    seen: list[str] = []
    for tok in (t.strip() for t in raw):
        if tok and tok != "貼上你的機器人Token" and tok not in seen:
            seen.append(tok)
    return seen


def find_ffmpeg() -> str:
    """找 ffmpeg 執行檔，依序：FFMPEG_PATH → PATH → 專案內常見位置，找不到就結束程式並說明

    Locate the ffmpeg executable. Search order: ``FFMPEG_PATH`` -> system PATH -> common places
    inside the project folder. Exits with a helpful message when it can't be found.
    """
    candidates = [
        os.environ.get("FFMPEG_PATH", ""),
        shutil.which("ffmpeg") or "",
        str(BASE / "ffmpeg" / "bin" / "ffmpeg.exe"),
        str(BASE / "ffmpeg.exe"),
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    raise SystemExit("找不到 ffmpeg。請安裝後加入 PATH，或在 .env 設定 FFMPEG_PATH=完整路徑")


# ============================================================
# settings.json（執行時設定）/ settings.json (runtime settings)
# ============================================================
def load_settings() -> None:
    """啟動時載入 settings.json；檔案不存在或壞掉就當作空的 / Load settings.json at startup (missing or broken = empty)."""
    try:
        _settings.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass


def save_settings() -> None:
    """把記憶體裡的設定寫回 settings.json / Write the in-memory settings back to settings.json."""
    try:
        SETTINGS_FILE.write_text(json.dumps(_settings, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        log.warning("無法儲存設定：%s", exc)


def get_setting(key: str, default=None):
    """讀一個設定值 / Read one setting."""
    return _settings.get(key, default)


def set_setting(key: str, value) -> None:
    """寫入一個設定值並立刻存檔；傳 None 代表刪除該設定

    Set one setting and save immediately. Passing ``None`` removes the key.
    """
    if value is None:
        _settings.pop(key, None)
    else:
        _settings[key] = value
    save_settings()


# ============================================================
# 看板存取模式與簽章金鑰 / Dashboard access mode and signing secret
# ============================================================
def dashboard_mode() -> str:
    """看板存取模式（DASHBOARD_ACCESS）
    open（預設）：知道網址的人都能控制所有頻道，不需要任何驗證，只適合信任的網路
    verify：要先用 Discord 確認身分：輸入 /help，點它給你的專屬連結（點一下就自動綁定，不用輸入任何碼）
            確認過的成員可以控制所有頻道，顯示真實的 Discord 暱稱，主機會記住他們的裝置，放公網時建議用這個
    voice：每人用 /help 的專屬連結進來，而且人要在語音頻道裡才能控制
    任何模式下，"更換 Bilibili 帳號"都只限機器人擁有者／本地

    Dashboard access mode (``DASHBOARD_ACCESS``):
      * open (default) - anyone who knows the URL can control every channel; only for trusted networks.
      * verify         - confirm identity through Discord first: type /help and open the personal link
                         (one click auto-binds the browser, nothing to type). Verified members can control all
                         channels and show their real Discord nickname; the host remembers their devices.
                         Recommended when the dashboard is exposed to the public internet.
      * voice          - everyone uses their own /help link AND must be in a voice channel to control playback.
    In every mode, switching the Bilibili account is limited to the bot owner / the local machine.
    """
    mode = os.environ.get("DASHBOARD_ACCESS", "open").strip().lower()
    return mode if mode in ("open", "verify", "voice") else "open"


def dashboard_open() -> bool:
    """是否為 open 模式 / True when the access mode is "open"."""
    return dashboard_mode() == "open"


def dashboard_secret() -> str:
    """後台簽章用的金鑰：第一次啟動時隨機產生並存檔，之後沿用（重開機器人，舊連結仍有效）

    The key used to sign dashboard links. Generated randomly on first use and saved, then reused
    (so existing links survive a bot restart). Treat settings.json as a secret file.
    """
    sec = _settings.get("dashboard_secret")
    if not isinstance(sec, str) or len(sec) < 32:
        sec = secrets.token_hex(32)
        set_setting("dashboard_secret", sec)
    return sec


# ============================================================
# 音質 / Audio quality
# ============================================================
def quality_for(guild_id: int | str) -> int:
    """該伺服器的音質：看板／指令切換的值 > .env 的 AUDIO_BITRATE > 預設 192

    Quality for one server. Priority: the value picked on the dashboard or via /quality
    > ``AUDIO_BITRATE`` in .env > the default 192 kbps.
    """
    saved = (_settings.get("quality") or {}).get(str(guild_id))
    if isinstance(saved, int) and saved in params.QUALITY_CHOICES:
        return saved
    return max(8, min(510, env_int("AUDIO_BITRATE", params.DEFAULT_BITRATE_KBPS)))


def set_quality_for(guild_id: int | str, kbps: int) -> bool:
    """記住某伺服器的音質；不在選項內回傳 False / Remember a server's quality; returns False if ``kbps`` isn't an allowed choice."""
    if kbps not in params.QUALITY_CHOICES:
        return False
    by = dict(_settings.get("quality") or {})
    by[str(guild_id)] = kbps
    set_setting("quality", by)
    return True


def target_bitrate(channel_kbps: int, guild_id: int | str) -> int:
    """Opus 編碼位元率：取"該伺服器的音質設定"與"語音頻道位元率"中較高者

    The Opus encoding bitrate: the higher of the server's quality setting and the voice
    channel's own bitrate, clamped to Opus' valid range (8-510 kbps).
    """
    return max(8, min(510, max(quality_for(guild_id), channel_kbps)))
