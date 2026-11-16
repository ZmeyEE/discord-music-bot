"""我的歌單的存檔：每位 Discord 使用者一棵樹，存在這台電腦的 library.json

存的只有連結和顯示用的資料（一首約 200 位元組，5000 首約 1 MB），不存聲音；原子寫入，寫到一半斷電不會壞檔
中繼站（VPS）上不存任何東西：它只是轉送，所以歌單只會在家裡這台電腦

Persistence of the library: one tree per Discord user, in library.json on this machine.
Only links and display data are stored (about 200 bytes a song, roughly 1 MB for 5000), never audio. Writes are atomic.
The relay (VPS) stores nothing: it only forwards, so playlists live on the home machine only.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from . import tree

log = logging.getLogger("musicbot")


class Library:
    """所有人的歌單 / Everyone's libraries."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.users: dict[str, dict] = {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.users = {str(k): v for k, v in dict(data.get("users", {})).items() if isinstance(v, dict) and v.get("type") == "folder"}
        except (OSError, ValueError):
            pass                                   # 沒有檔案或壞掉就當作空的 / missing or corrupt: start empty

    def root(self, user: str) -> dict:
        """這個人的樹；沒有就建一棵空的（還不存檔，等有改動才存）/ This person's tree; an empty one is created (not saved until something changes)."""
        if user not in self.users:
            self.users[user] = tree.new_root()
        return self.users[user]

    def save(self) -> None:
        """原子寫入：先寫暫存檔再取代 / Atomic write: temp file first, then replace."""
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps({"users": self.users}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as exc:
            log.warning("無法儲存歌單：%s", exc)
