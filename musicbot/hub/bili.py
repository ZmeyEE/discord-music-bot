"""Bilibili 登入：啟動時檢查、掃碼登入流程

Bilibili login: the start-up check and the QR login flow
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from .. import bilibili, params, sources
from .models import Emit

if TYPE_CHECKING:
    pass
log = logging.getLogger("musicbot")


class BiliMixin:
    def _notify_all(self) -> None:
        """通知所有伺服器的看板重新整理 / Ask the dashboard of every server to refresh."""
        for g in self.primary.guilds:
            self.notify(g.id)

    async def refresh_bili(self) -> None:
        """啟動時確認已記住的 Bilibili 登入是否仍有效（過期就清掉，避免拿失效 cookie 去請求）

        At start-up, check that the remembered Bilibili login is still valid (an expired one is cleared so
        we don't send requests with a dead cookie).
        """
        if not bilibili.COOKIE_FILE.exists():
            return
        try:
            acc = await bilibili.fetch_account()
        except bilibili.BiliError as exc:
            log.warning("暫時無法確認 Bilibili 登入狀態：%s", exc)
            return
        if acc is None:
            log.info("Bilibili 登入已過期，已清除")
            bilibili.logout()
        else:
            bilibili.remember_account(acc)
            log.info("Bilibili 已登入：%s（%s）", acc["name"], acc["vip_label"])
        self._notify_all()

    async def bili_login_flow(self, emit: Emit) -> None:
        """QR 掃碼登入：產生 QR → 輪詢掃碼狀態 → 存 cookie → 記住帳號，進度用 emit 回報給發起的那個瀏覽器

        QR-code login: generate a QR -> poll the scan status -> save the cookies -> remember the account.
        Progress is reported through ``emit`` to the browser that started the flow.
        """
        try:
            url, key = await bilibili.qr_generate()
            await emit({"type": "bili_qr", "img": bilibili.qr_image(url), "ttl": params.QR_LIFETIME})
            deadline = time.monotonic() + params.QR_LIFETIME + 5
            last = None
            while time.monotonic() < deadline:
                await asyncio.sleep(2)
                code, cookies = await bilibili.qr_poll(key)
                if code == bilibili.CODE_OK and cookies:
                    bilibili.save_cookies(cookies)
                    acc = await bilibili.fetch_account()
                    bilibili.remember_account(acc)
                    sources.clear_search_cache()
                    log.info("Bilibili 登入成功：%s", acc["name"] if acc else "?")
                    self._notify_all()
                    await emit({"type": "bili_status", "status": "ok", "account": acc})
                    return
                if code == bilibili.CODE_EXPIRED:
                    break
                if code != last:
                    last = code
                    status = "scanned" if code == bilibili.CODE_SCANNED else "waiting"
                    await emit({"type": "bili_status", "status": status})
            await emit({"type": "bili_status", "status": "expired"})
        except bilibili.BiliError as exc:
            await emit({"type": "bili_status", "status": "error", "text": str(exc)})
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("Bilibili 登入流程失敗")
            await emit({"type": "bili_status", "status": "error", "text": f"登入失敗：{str(exc)[:120]}"})
