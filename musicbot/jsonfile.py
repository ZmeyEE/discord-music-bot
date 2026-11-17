"""JSON 存檔的共用小工具：安全讀取（壞檔先備份）和真正的原子寫入

用在 members.json、library.json、spotify_tokens.json、settings.json

Shared helpers for JSON files: a safe read (a broken file is kept aside first) and a really atomic write.
Used by members.json, library.json, spotify_tokens.json and settings.json.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

log = logging.getLogger("musicbot")


def read_dict(path: Path | str) -> dict:
    """讀一個 JSON 檔，回傳最外層的字典；檔案不存在是空的。壞掉（或最外層不是字典）就改名備份成 *.bad-時間，再當作空的

    這樣下一次存檔不會把壞檔直接蓋掉，使用者還有機會手動救回來
    Read a JSON file as a dict; a missing file is empty. A broken file (or one whose top level is not a dict) is renamed to *.bad-<time> and treated as empty,
    so the next save cannot overwrite it and the data can still be rescued by hand.
    """
    p = Path(path)
    try:
        raw = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        log.warning("讀不到 %s：%s", p.name, exc)
        return {}
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except ValueError:
        pass
    bad = p.with_name(f"{p.name}.bad-{time.strftime('%Y%m%d-%H%M%S')}")
    n = 1
    while bad.exists():                         # 同一秒壞兩次也不要蓋掉前一份備份 / two breaks in one second must not overwrite the earlier backup
        n += 1
        bad = p.with_name(f"{p.name}.bad-{time.strftime('%Y%m%d-%H%M%S')}-{n}")
    try:
        os.replace(p, bad)
        log.warning("%s 壞掉了，已改名備份成 %s，從空的開始", p.name, bad.name)
    except OSError:
        log.warning("%s 壞掉了，而且無法備份，從空的開始", p.name)
    return {}


def write_text(path: Path | str, text: str) -> None:
    """原子寫入：寫到暫存檔、fsync、再取代；斷電時不是舊的完整檔就是新的完整檔（會丟 OSError）

    Atomic write: temp file, fsync, replace; after a power cut the file is either the whole old one or the whole new one (raises OSError).
    """
    p = Path(path)
    tmp = p.with_name(p.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)
