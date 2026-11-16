"""連線與驗證的上限：每個 IP 的連線數、頻率、握手失敗封鎖

Connection and auth limits: per-IP connections, rate, lock-out after failed handshakes
"""
from __future__ import annotations

import logging
import time
from collections import deque

from .. import params

log = logging.getLogger("musicbot")


class LimitsMixin:
    def _admit_browser(self, ip: str) -> bool:
        """這個 IP 還可以再開一個瀏覽器連線嗎？（同時數 + 每分鐘新連線數）

        May this IP open another browser connection? (Checks both concurrent count and new-per-minute rate.)
        """
        now = time.monotonic()
        hist = self._new_conns.setdefault(ip, deque())
        while hist and now - hist[0] > 60:
            hist.popleft()
        if len(hist) >= params.NEW_PER_MINUTE or self._per_ip.get(ip, 0) >= params.MAX_PER_IP:
            return False
        hist.append(now)
        self._per_ip[ip] = self._per_ip.get(ip, 0) + 1
        return True

    def _release_browser(self, ip: str) -> None:
        """瀏覽器離線時歸還名額 / Give the slot back when a browser disconnects."""
        n = self._per_ip.get(ip, 0) - 1
        if n > 0:
            self._per_ip[ip] = n
        else:
            self._per_ip.pop(ip, None)
        if not self._new_conns.get(ip):
            self._new_conns.pop(ip, None)

    def _locked(self, ip: str) -> bool:
        """這個 IP 目前被封鎖嗎？封鎖到期會自動解除 / Is this IP currently locked out? Expired lock-outs are lifted automatically."""
        until = self._locked_until.get(ip, 0.0)
        if until and time.monotonic() >= until:
            self._locked_until.pop(ip, None)
            self._auth_fails.pop(ip, None)
            return False
        return bool(until)

    def _record_auth_failure(self, ip: str) -> None:
        """記一次握手失敗；視窗內達上限就封鎖 / Record a failed handshake; lock the IP out once the limit is hit within the window."""
        now = time.monotonic()
        fails = [t for t in self._auth_fails.get(ip, []) if now - t < params.AUTH_FAIL_WINDOW] + [now]
        self._auth_fails[ip] = fails
        if len(fails) >= params.AUTH_FAIL_LIMIT:
            self._locked_until[ip] = now + params.AUTH_LOCKOUT
            log.warning("來源 %s 握手失敗 %d 次，封鎖 %d 分鐘", ip, len(fails), int(params.AUTH_LOCKOUT // 60))
