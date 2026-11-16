"""啟動時的調整與檢查：davey 版本、重連等待上限、Windows 效能

Start-up tweaks and checks: the davey version, the reconnect delay cap, Windows tuning
"""
from __future__ import annotations

import os

from . import params


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


def cap_reconnect_delay(max_exp: int = params.RECONNECT_MAX_EXP) -> None:
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
