"""成員登錄（驗證模式用）

驗證過的 Discord 成員與他們的"裝置憑證"，存在執行機器人的這台電腦（members.json），
不放在中繼站，所以中繼站即使被入侵也洩漏不了任何東西
瀏覽器裡存的是一把隨機長憑證；主機只存它的 SHA-256 雜湊，所以 members.json 外流也無法拿來冒用

登記的方式只有一種：使用者在 Discord 輸入 /help，點它給的專屬連結（簽章憑證綁定他的身分）
連結一打開，主機就替那個瀏覽器登記一把裝置憑證，之後同一個瀏覽器不用再點連結

Member registry (used by the "verify" access mode).

Keeps the verified Discord members and their *device tokens*. It is stored on the machine running the
bot (members.json), never on the relay, so even a compromised relay leaks nothing. The browser keeps a
long random token; the host only stores its SHA-256 hash, so a leaked members.json cannot be replayed.

There is exactly one way to register: the user types /help in Discord and opens the personal link
(a signed token bound to their identity). When the link is opened, the host registers a device token
for that browser, so the same browser doesn't need the link again.
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
import time
from pathlib import Path
from . import jsonfile, params

log = logging.getLogger("musicbot")



def _h(token: str) -> str:
    """憑證的 SHA-256 雜湊（磁碟上只存這個） / SHA-256 hash of a token (the only form stored on disk)."""
    return hashlib.sha256(token.encode()).hexdigest()


class Registry:
    """裝置憑證登錄簿：新增、查詢、撤銷，並自動存檔

    The device registry: add, look up and revoke device tokens, persisting every change to JSON.
    ``devices`` maps ``sha256(token)`` -> ``{uid, name, gid, created, seen}``.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.devices: dict[str, dict] = {}
        devices = jsonfile.read_dict(self.path).get("devices", {})      # 不存在 = 空的；壞掉會先備份 / missing = empty; a broken file is kept aside first
        self.devices = {k: v for k, v in devices.items() if isinstance(v, dict)} if isinstance(devices, dict) else {}

    def _save(self) -> None:
        """原子寫入：先寫暫存檔再取代，避免寫到一半斷電造成檔案損毀

        Atomic write: write a temp file, then replace, so a crash mid-write can't corrupt the file.
        """
        try:
            jsonfile.write_text(self.path, json.dumps({"devices": self.devices}, ensure_ascii=False, indent=1))
        except OSError as exc:
            log.warning("無法儲存成員登錄：%s", exc)

    def add_device(self, uid: int, name: str, gid: int) -> str:
        """登記一個新裝置，回傳要交給瀏覽器保存的憑證（主機只存雜湊）

        Register a new device and return the token to hand to the browser (the host stores only the hash).
        """
        token = secrets.token_urlsafe(32)
        now = time.time()
        self._prune(str(uid), str(gid), now)
        self.devices[_h(token)] = {"uid": str(uid), "name": name, "gid": str(gid), "created": now, "seen": now}
        self._save()
        return token

    def _prune(self, uid: str, gid: str, now: float) -> None:
        """登記新裝置前先清：過期的刪掉，同一個人在同一個伺服器最多留 DEVICE_MAX_PER_USER - 1 個最近用過的（連結重新整理一次就領一把，不清會越積越多）
        Before adding a device: drop the expired ones and keep at most DEVICE_MAX_PER_USER - 1 recent ones for this person in this server (every refresh of a link would otherwise add one more).
        """
        for k in [k for k, r in self.devices.items() if now - r.get("seen", 0) > params.DEVICE_TTL]:
            del self.devices[k]
        mine = sorted((k for k, r in self.devices.items() if r.get("uid") == uid and r.get("gid") == gid), key=lambda k: self.devices[k].get("seen", 0))
        for k in mine[: max(0, len(mine) - (params.DEVICE_MAX_PER_USER - 1))]:
            del self.devices[k]

    def lookup(self, token: str) -> dict | None:
        """用憑證找出登記資料；過期就刪掉並回傳 None，使用中則順延效期

        Find the record for a token. Expired tokens are deleted (returns None); a valid use refreshes "seen".
        """
        if not token or len(token) > 200:   # 擋掉明顯不合理的輸入 / reject obviously bogus input early
            return None
        key = _h(token)
        rec = self.devices.get(key)
        if rec is None:
            return None
        now = time.time()
        if now - rec["seen"] > params.DEVICE_TTL:
            del self.devices[key]
            self._save()
            return None
        if now - rec["seen"] > params.SEEN_RESOLUTION:
            rec["seen"] = now
            self._save()
        return rec

    def revoke_user(self, uid: int) -> int:
        """撤銷某個使用者的所有裝置，回傳撤銷數量（/unverify 用）

        Revoke every device of one user and return how many were removed (used by /unverify).
        """
        gone = [k for k, r in self.devices.items() if r["uid"] == str(uid)]
        for k in gone:
            del self.devices[k]
        if gone:
            self._save()
        return len(gone)

    def devices_of(self, uid: int) -> list[dict]:
        """列出某個使用者目前登記的裝置 / List the devices currently registered for one user."""
        return [r for r in self.devices.values() if r["uid"] == str(uid)]
