"""每個人連結的 Spotify 帳號：憑證存檔，以及授權進行到一半的暫存

憑證存在這台電腦的 spotify_tokens.json（不進 git、不傳到中繼站）；refresh token 等於這個人的 Spotify 讀取權限，所以只有檔案本身有，網頁拿不到
Each person's linked Spotify account: the tokens on disk, and the half-finished authorisations in memory.
The tokens live in spotify_tokens.json on this machine (not in git, never sent to the relay). A refresh token is this person's read access to Spotify,
so only the file has it; the page never gets it.
"""
from __future__ import annotations

import json
import logging
import secrets
import time
from pathlib import Path

from .. import jsonfile, params

log = logging.getLogger("musicbot")


class Accounts:
    """所有人的 Spotify 憑證 / Everyone's Spotify tokens."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.users: dict[str, dict] = {}
        self.pending: dict[str, dict] = {}        # state -> {user, verifier, until}
        users = jsonfile.read_dict(self.path).get("users", {})
        if isinstance(users, dict):
            self.users = {str(k): v for k, v in users.items() if isinstance(v, dict) and v.get("refresh")}

    def save(self) -> None:
        """原子寫入 / Atomic write."""
        try:
            jsonfile.write_text(self.path, json.dumps({"users": self.users}, ensure_ascii=False))
        except OSError as exc:
            log.warning("無法儲存 Spotify 憑證：%s", exc)

    def begin(self, user: str, verifier: str) -> str:
        """開始一次授權，回傳 state（網址上帶著，貼回來時用它對回這次授權）/ Start an authorisation; returns the state carried in the address and matched when it comes back."""
        now = time.time()
        self.pending = {k: v for k, v in self.pending.items() if v["until"] > now}      # 順便清掉過期的 / drop the expired ones meanwhile
        state = secrets.token_urlsafe(16)
        self.pending[state] = {"user": user, "verifier": verifier, "until": now + params.SPOTIFY_PENDING_SECONDS}
        return state

    def finish(self, user: str, state: str) -> str | None:
        """貼回來的 state 對得上、沒過期、而且是同一個人發起的，就回傳當初的 verifier（只能用一次）；否則 None

        Returns the verifier when the pasted state matches, has not expired and was started by the same person (usable once); otherwise None.
        """
        item = self.pending.get(state)
        if item and item["until"] < time.time():
            self.pending.pop(state, None)
            return None
        if not item or item["user"] != user:        # 別人貼來的不算數，也不會害發起的人的授權作廢 / someone else's attempt counts for nothing and doesn't spoil the starter's authorisation
            return None
        del self.pending[state]
        return item["verifier"]

    def link(self, user: str, tokens: dict, name: str) -> None:
        self.users[user] = {**tokens, "name": name}
        self.save()

    def unlink(self, user: str) -> bool:
        gone = self.users.pop(user, None) is not None
        if gone:
            self.save()
        return gone
