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
import re
from logging.handlers import RotatingFileHandler

import discord

from . import commands, config, netinfo
from .dashboard import Dashboard
from .health import HealthMonitor
from .hub import Hub
from .paths import LOG_DIR, WEB_DIR
from .player import PlayerBot

log = logging.getLogger("musicbot")


# ============================================================
# 啟動前檢查 / Pre-flight checks
# ============================================================
def check_davey_compat() -> None:
    """davey 0.2.x 與 discord.py 2.7.x 不相容：語音能連線、頭像有綠框，但頻道內完全沒聲音，啟動時就擋下來

    davey 0.2.x is incompatible with discord.py 2.7.x: the bot joins voice and shows the green ring, but
    the channel hears nothing (the end-to-end encryption handshake silently fails). Stop at start-up with
    a clear message instead of letting people debug a "silent bot". Remove this check once discord.py
    supports davey 0.2+ (and lift the version cap in requirements.txt).
    """
    try:
        from importlib.metadata import version

        dv = version("davey")
        major_minor = tuple(int(x) for x in dv.split(".")[:2])
    except Exception:  # noqa: BLE001 - 沒裝或版本字串怪怪的就交給 discord.py 處理 / not installed or odd version string: let discord.py deal with it
        return
    if major_minor >= (0, 2):
        raise SystemExit(
            f"偵測到 davey {dv}，它與目前的 discord.py 不相容（機器人會進語音頻道，但沒有聲音）。\n"
            '請執行：.venv\\Scripts\\python.exe -m pip install "davey>=0.1.0,<0.2"\n'
            "（discord.py 支援 davey 0.2 之後，可移除這項檢查與 requirements.txt 的版本上限）"
        )


def cap_reconnect_delay(max_exp: int = 4) -> None:
    """把 discord.py 斷線重連的等待上限從約 17 分鐘縮到 16 秒

    discord.py waits uniform(0, 2^n) seconds between reconnects, n up to 10, and only resets after ~34 minutes
    of calm. After two outages in one night a bot could sleep 2-3 minutes (up to 17) after Discord was already
    back. Cap n at ``max_exp`` (2^4 = 16 s) for both the gateway and the voice reconnect loops.
    """
    from discord import client, voice_state
    from discord.backoff import ExponentialBackoff

    class _CappedBackoff(ExponentialBackoff):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self._max = max_exp

    client.ExponentialBackoff = _CappedBackoff
    voice_state.ExponentialBackoff = _CappedBackoff


def tune_process() -> dict:
    """Windows：優先權調高一級、關掉省電降速（EcoQoS）、計時精度 1 ms，回傳實際套用了哪些
    TUNE_PROCESS=0 可以關掉

    Windows: raise the priority one step, turn off the power throttling (EcoQoS) and ask for 1 ms timer
    resolution, so a minimised console or a busy PC doesn't delay the 20 ms audio packets.
    Returns what was really applied. Set TUNE_PROCESS=0 to skip. Other systems do nothing.
    Measured on the dev PC (i5-12400F): 120 simultaneous channels need 30% of one core and no packet was late,
    so this is protection against Windows throttling, not a fix for a CPU limit.
    """
    done: dict = {}
    if os.name != "nt" or os.environ.get("TUNE_PROCESS", "1") == "0":
        return done
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]     # 不給型別的話 64 位元的代號會被截成 32 位元 / without types a 64-bit handle gets cut to 32 bits
    k32.SetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    handle = k32.GetCurrentProcess()
    try:
        done["priority"] = bool(k32.SetPriorityClass(handle, 0x00008000))        # ABOVE_NORMAL_PRIORITY_CLASS
    except Exception:  # noqa: BLE001 - 調不了就算了，不影響播放 / if it can't be set, playback still works
        pass

    class _Throttle(ctypes.Structure):
        _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG), ("StateMask", wintypes.ULONG)]

    try:
        state = _Throttle(1, 1, 0)   # Version 1, 控制 EXECUTION_SPEED 這一項，狀態 0 = 不要降速 / control the EXECUTION_SPEED bit, state 0 = never throttle
        done["no_throttle"] = bool(k32.SetProcessInformation(handle, 4, ctypes.byref(state), ctypes.sizeof(state)))   # 4 = ProcessPowerThrottling
    except Exception:  # noqa: BLE001
        pass
    try:
        done["timer_1ms"] = ctypes.WinDLL("winmm").timeBeginPeriod(1) == 0
    except Exception:  # noqa: BLE001
        pass
    return done


# ============================================================
# 紀錄 / Logging
# ============================================================
class _RedactSecrets(logging.Filter):
    """寫進除錯記錄前，遮蔽語音閘道訊息中的權杖與加密金鑰

    Log filter that masks tokens and encryption keys found in voice-gateway messages
    before they are written to the debug log, so the log file is safe to share.
    """

    _PATTERNS = (
        (re.compile(r"('token':\s*')[^']*"), r"\1***"),
        (re.compile(r"('secret_key':\s*\[)[^\]]*"), r"\1***"),
    )

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for pattern, repl in self._PATTERNS:
            msg = pattern.sub(repl, msg)
        record.msg, record.args = msg[:600], ()   # 同時截短，避免單行過長 / also truncate overly long lines
        return True


def setup_logging() -> None:
    """設定紀錄：畫面 + logs/bot.log（輪替）；VOICE_DEBUG=1 時另寫詳細的語音除錯記錄

    Configure logging: console + a rotating ``logs/bot.log``. With ``VOICE_DEBUG=1`` an extra, verbose
    ``logs/voice-debug.log`` captures the voice handshake (secrets are redacted).
    """
    LOG_DIR.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handlers = [
        logging.StreamHandler(),
        RotatingFileHandler(LOG_DIR / "bot.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8"),
    ]
    for h in handlers:
        h.setLevel(logging.INFO)
        h.setFormatter(fmt)
    logging.basicConfig(level=logging.INFO, handlers=handlers)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)   # 不記每一個 HTTP 請求 / don't log every HTTP request

    if os.environ.get("VOICE_DEBUG", "").strip() in ("1", "true", "yes"):
        # 詳細的語音／端對端加密（DAVE）握手記錄，排查"沒聲音"用，權杖與金鑰會被遮蔽
        # Verbose voice / end-to-end-encryption (DAVE) handshake log for debugging "no sound". Secrets are masked.
        dbg = RotatingFileHandler(LOG_DIR / "voice-debug.log", maxBytes=2_000_000, backupCount=1, encoding="utf-8")
        dbg.setFormatter(fmt)
        dbg.addFilter(_RedactSecrets())
        for name in ("discord.gateway", "discord.voice_state", "discord.voice_client"):
            lg = logging.getLogger(name)
            lg.setLevel(logging.DEBUG)
            lg.addHandler(dbg)


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
        await asyncio.gather(*(start_worker(w, t) for w, t in zip(hub.workers, tokens)))
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
