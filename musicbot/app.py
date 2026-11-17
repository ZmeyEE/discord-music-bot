"""程式進入點：讀設定、啟動後台、啟動主機器人與所有分身

Application entry point: load the settings, start the dashboard, then start the main bot and every clone.

Start-up order in ``main()`` / 啟動順序:
  1. read .env + settings.json        2. set up logging        3. sanity-check the davey version
  4. collect bot tokens               5. ``run()``: Hub -> dashboard -> (optional) relay client
     -> health monitor -> log in every bot account at the same time.
"""
from __future__ import annotations

import asyncio
import logging
import os

import discord

from . import commands, config, netinfo
from .dashboard import Dashboard
from .health import HealthMonitor
from .hub import Hub
from .logging_setup import setup_logging
from .paths import WEB_DIR
from .player import PlayerBot
from .tuning import cap_reconnect_delay, check_davey_compat, tune_process

log = logging.getLogger("musicbot")


def _announce_dashboard(hub: Hub, host: str, port: int) -> None:
    """在紀錄裡印出看板網址（以及朋友可能連得到的位址）

    Print the dashboard URL in the log (and, when it listens beyond localhost, addresses friends may use).
    """
    log.info("網頁後台已啟動：%s（監聽 %s:%d）", hub.base_url, host, port)
    if host in ("127.0.0.1", "localhost", "::1"):
        log.info("目前只有這台電腦能開看板。要讓朋友一起用，請見 README「讓朋友一起用」。")
        return
    for c in netinfo.candidates(port):
        log.info("  朋友可嘗試的網址：%s（%s）", c.url, c.label)


# ============================================================
# 主流程 / Main run loop
# ============================================================
async def run(tokens: list[str]) -> None:
    """建立 Hub、後台、中繼連線與健康偵測，然後同時登入所有機器人帳號

    Build the Hub, dashboard, relay client and health monitor, then log in every bot account concurrently.
    ``tokens[0]`` is the main bot; the rest are clones.
    """
    hub = Hub()
    hub.workers = [PlayerBot(hub, i) for i in range(len(tokens))]   # 一個 token = 一個 PlayerBot / one token = one PlayerBot
    commands.register(hub)

    # --- 後台位址與埠 / dashboard host, port and public URL ---
    host = os.environ.get("DASHBOARD_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = config.env_int("DASHBOARD_PORT", 8765)
    hub.base_url = os.environ.get("DASHBOARD_URL", "").strip().rstrip("/") or f"http://localhost:{port}"
    relay_url = os.environ.get("RELAY_URL", "").strip()
    if relay_url and not os.environ.get("DASHBOARD_URL", "").strip():
        # 有中繼站時，/help 給的網址就是中繼站的網址（朋友從那裡進來）
        # With a relay, the URL that /help hands out is the relay's address (friends come in through it).
        hub.base_url = relay_url.rstrip("/").replace("ws://", "http://", 1).replace("wss://", "https://", 1)
    hub.dashboard = Dashboard(hub, WEB_DIR, host, port)
    if (host not in ("127.0.0.1", "localhost", "::1") and not relay_url
            and not os.environ.get("DASHBOARD_URL", "").strip()):
        best = netinfo.best_url(port)          # 開放區網／虛擬網路時，自動挑朋友最可能連得到的位址 / when exposed to LAN/VPN, pick the address friends most likely reach
        if best:
            hub.base_url = best.url
    try:
        await hub.dashboard.start()
    except OSError as exc:
        # 寧可直接停下來，也不要"機器人在跑、看板卻是死的"：
        # 最常見原因是另一個機器人視窗還開著（兩個實例用同一個 Token 會互相打架）
        # Better to stop than to run a bot with a dead dashboard. Most common cause: another bot
        # window is still open (two instances sharing one token fight each other).
        raise SystemExit(
            f"無法啟動網頁後台：連接埠 {port} 已被占用（{exc.strerror or exc}）。\n"
            "通常是「機器人已經在另一個視窗執行中」。請先關掉另一個機器人視窗再啟動；\n"
            "如果確定沒有，可能是別的程式占用了，請在 .env 設定 DASHBOARD_PORT=另一個埠號。"
        ) from exc
    _announce_dashboard(hub, host, port)

    async def start_worker(worker: PlayerBot, token: str) -> None:
        """登入一個機器人；分身 Token 無效就略過，主機器人無效則中止

        Log one bot in. An invalid clone token is skipped; an invalid main-bot token aborts start-up.
        """
        try:
            await worker.start(token)
        except discord.LoginFailure:
            if worker.is_primary:
                raise
            log.error("分身 %d 的 Token 無效，已略過", worker.index)

    if len(tokens) > 1:
        log.info("共 %d 個機器人帳號（1 個主機器人 + %d 個分身，分身沒有數量上限）；"
                 "卡頓偵測器會在確定是新加入的頻道造成卡頓時，從最後加入的開始逐個停止並公告", len(tokens), len(tokens) - 1)

    # --- 中繼站（選用）/ relay (optional) ---
    relay_task = None
    relay_url = os.environ.get("RELAY_URL", "").strip()
    if relay_url:   # 看板放在 VPS／樹莓派上的中繼站：這裡主動連出去，不需要在家裡開任何埠 / dashboard lives on a VPS/Raspberry Pi relay: we dial out, no home port needed
        relay_key = os.environ.get("RELAY_KEY", "").strip()
        if len(relay_key) < 16:
            log.error("有設定 RELAY_URL，但 RELAY_KEY 不見了或太短（至少 16 字元），不會連線到中繼站")
        else:
            from .relay_client import RelayClient
            relay = RelayClient(hub, relay_url, relay_key)
            relay_task = asyncio.create_task(relay.run())
            log.info("將連線到中繼站：%s", relay_url)

    monitor_task = asyncio.create_task(HealthMonitor(hub).run())   # 背景偵測播放卡頓（見 health.py）/ background stutter detection (see health.py)
    try:
        # 某一個分身啟動時出了別的錯（網路暫時不通等），不要連累其他機器人 / one clone failing to start for another reason (a network blip...) must not take the others down
        results = await asyncio.gather(*(start_worker(w, t) for w, t in zip(hub.workers, tokens)), return_exceptions=True)
        for w, r in zip(hub.workers, results):
            if isinstance(r, BaseException) and not isinstance(r, asyncio.CancelledError):
                log.error("[%s] 啟動失敗：%r", w.label, r)
    finally:
        # 收尾：停掉背景工作、關閉所有機器人與後台 / cleanup: stop background tasks, close all bots and the dashboard
        monitor_task.cancel()
        if relay_task:
            relay_task.cancel()
        for w in hub.workers:
            await w.close()
        if hub.dashboard:
            await hub.dashboard.stop()


def main() -> None:
    """同步的進入點（bot.py 呼叫它） / The synchronous entry point called by bot.py."""
    config.load_env()
    config.load_settings()
    setup_logging()
    check_davey_compat()
    cap_reconnect_delay()
    tuned = tune_process()
    if tuned:
        log.info("效能調整：%s", "、".join(k for k, v in tuned.items() if v) or "沒有成功的項目")
    tokens = config.discord_tokens()
    if not tokens:
        raise SystemExit("尚未設定 DISCORD_TOKEN：請複製 .env.example 為 .env 並填入 Token")
    try:
        asyncio.run(run(tokens))
    except KeyboardInterrupt:
        pass
    except discord.LoginFailure:
        raise SystemExit("DISCORD_TOKEN 無效：請到 Discord Developer Portal 重新產生 Token")
