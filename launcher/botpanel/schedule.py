r"""每日定時重啟的設定與時間計算（不碰畫面）

Daily scheduled restart: the settings file and the time maths (no UI).
設定存在 %APPDATA%\MusicBotLauncher\schedule.json（和記住專案位置的 launcher.json 同一個資料夾，但分開存，互不覆蓋）
Stored in %APPDATA%\MusicBotLauncher\schedule.json, next to launcher.json but in its own file so neither overwrites the other.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from .paths import user_config_path

DEFAULT_TIME = "04:00"        # 第一次打開設定時預設的時間 / the time shown the first time the dialog opens
GRACE_SECONDS = 600           # 錯過時間超過這麼久（電腦睡著、面板被卡住）就跳過今天，不要半夜錯過卻中午突然重啟 / missed by more than this (PC asleep...): skip today instead of restarting out of the blue later
TICK_MS = 15_000              # 多久看一次時間 / how often the clock is checked


def settings_path() -> Path:
    """設定檔位置 / Where the settings live."""
    return user_config_path().with_name("schedule.json")


def parse_time(text: str) -> str | None:
    """"4:5" / "04:05" -> "04:05"；不是 0:00~23:59 就回傳 None / Normalise to HH:MM, or None when it is not a valid time of day."""
    try:
        h, m = str(text).strip().split(":")
        h, m = int(h), int(m)
    except ValueError:
        return None
    return f"{h:02d}:{m:02d}" if 0 <= h <= 23 and 0 <= m <= 59 else None


def load(path: Path | None = None) -> tuple[bool, str]:
    """讀 (開關, 時間)；沒有檔或壞掉就是 (關, 預設時間) / Read (enabled, time); a missing or broken file means (off, default time)."""
    try:
        data = json.loads((path or settings_path()).read_text(encoding="utf-8-sig"))
        return bool(data.get("enabled")), parse_time(data.get("time", "")) or DEFAULT_TIME
    except (OSError, ValueError, AttributeError):
        return False, DEFAULT_TIME


def save(enabled: bool, hhmm: str, path: Path | None = None) -> None:
    """存 (開關, 時間)；寫不進去就丟 OSError / Save (enabled, time); raises OSError when it cannot be written."""
    p = path or settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"enabled": bool(enabled), "time": hhmm}, ensure_ascii=False, indent=1), encoding="utf-8")


def next_run(now: datetime, hhmm: str) -> datetime:
    """下一次要重啟的時間（一定比 now 晚）/ The next restart moment, always later than ``now``."""
    h, m = (int(x) for x in hhmm.split(":"))
    at = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return at if at > now else at + timedelta(days=1)


def verdict(now: datetime, due: datetime) -> str:
    """"wait"（還沒到）／"fire"（到了，現在重啟）／"skip"（錯過太久，略過這次）/ not yet / restart now / missed too long ago, skip it."""
    late = (now - due).total_seconds()
    if late < 0:
        return "wait"
    return "fire" if late <= GRACE_SECONDS else "skip"
