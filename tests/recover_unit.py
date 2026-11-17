"""斷線救援的單元測試（不需要 Discord 或 harness）：重連等待上限、語音被踢後接著播
Unit tests for outage recovery (no Discord or harness needed): the reconnect delay cap, and resuming after a voice kick

用 tests/run_all.py 執行 / run it with tests/run_all.py
"""
import asyncio
import os
import sys
import time
from collections import deque
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 專案根目錄 / project root
sys.path.insert(0, ROOT)
import discord
from musicbot import player as P
from musicbot import params
from musicbot.app import cap_reconnect_delay
from musicbot.player import GuildState, PlayerBot

res = []
def check(n, ok, d=""): res.append(bool(ok)); print(("PASS" if ok else "FAIL"), n, str(d)[:190], flush=True)

# ============ 重連等待上限 ============
cap_reconnect_delay()
b = discord.client.ExponentialBackoff()
worst = max(b.delay() for _ in range(60))
check("B1 gateway 重連等待上限 <= 16 秒（原本最多約 1024 秒）", worst <= 16.0, worst)
check("B2 語音重連用同一個上限", discord.voice_state.ExponentialBackoff is discord.client.ExponentialBackoff)


# ============ Windows 效能調整 ============
if os.name == "nt":
    import ctypes
    from musicbot.app import tune_process
    got = tune_process()
    k32 = ctypes.WinDLL("kernel32")
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    k32.GetPriorityClass.argtypes = [ctypes.c_void_p]
    check("W1 優先權設成高於一般", got.get("priority") and k32.GetPriorityClass(k32.GetCurrentProcess()) == 0x8000, got)
    check("W2 省電降速與 1ms 計時都套用成功", got.get("no_throttle") and got.get("timer_1ms"), got)
    os.environ["TUNE_PROCESS"] = "0"
    check("W3 TUNE_PROCESS=0 時什麼都不做", tune_process() == {})
    del os.environ["TUNE_PROCESS"]


# ============ 語音被踢後接著播 ============
class Chan:
    def __init__(self, humans): self.id = 7; self.members = [SimpleNamespace(bot=False)] * humans


class Guild:
    def __init__(self, humans=1):
        self.id, self.name, self.voice_client = 1, "g", None
        self.channel = Chan(humans)
    def get_channel(self, i): return self.channel


def make(guild, drop_ago):
    """建一個不連 Discord 的 PlayerBot / a PlayerBot that never touches Discord"""
    w = PlayerBot.__new__(PlayerBot)
    w.hub, w.index, w.is_primary = SimpleNamespace(notify=lambda g: None), 1, False
    w.states, w._recover_tasks, w._enrich_sem, w._watch_task = {}, {}, None, None
    w._gateway_drop = time.monotonic() - drop_ago
    w._connection = SimpleNamespace(user=SimpleNamespace(name="t", id=5))   # Client.user 唯讀，從這裡取 / Client.user is read-only, it reads from here
    w.get_guild = lambda gid: guild
    w.is_closed = lambda: False
    w.is_ready = lambda: True
    w._connected = []
    async def ensure_voice(g, channel=None):
        g.voice_client = SimpleNamespace(channel=g.channel); w._connected.append(1); return g.voice_client
    async def ensure_playing(g): w._played = True
    async def _say(st, text): w._said = text
    w.ensure_voice, w.ensure_playing, w._say = ensure_voice, ensure_playing, _say
    w._played, w._said = False, ""
    return w


REAL_SLEEP = asyncio.sleep   # patch 會換掉整個 asyncio.sleep，先留一份 / the patch replaces asyncio.sleep globally, keep the real one
async def fast_sleep(_): await REAL_SLEEP(0)


async def main():
    # 1) 閘道剛斷線 + 語音被踢：歌放回最前面、記住進度、啟動救援
    g = Guild(); w = make(g, drop_ago=30)
    st = w.state(1); st.last_voice_id = 7
    t = SimpleNamespace(id="a", title="song"); t2 = SimpleNamespace(id="b", title="next")
    st.current, st.started_at, st.queue = t, time.monotonic() - 42, deque([t2])
    await w.on_track_end(g, None)
    check("R1 歌放回待播最前面", [x.id for x in st.queue] == ["a", "b"], [x.id for x in st.queue])
    check("R2 記住進度約 42 秒", 41 <= st.start_offset <= 44 and st.start_offset_id == "a", st.start_offset)
    check("R3 啟動了回頻道的背景工作", st.recovering and 1 in w._recover_tasks)
    with mock.patch.object(asyncio, "sleep", fast_sleep):
        await w._recover_tasks[1]
    check("R4 恢復後回頻道並開始播", w._connected and w._played and g.voice_client is not None)
    check("R5 回來後有發訊息、狀態清掉", "回來了" in w._said and not st.recovering and 1 not in w._recover_tasks)

    # 2) 一般播完（語音還在）：不啟動救援
    g = Guild(); w = make(g, drop_ago=30); st = w.state(1)
    g.voice_client = SimpleNamespace(channel=g.channel)
    st.current, st.started_at = t, time.monotonic() - 100
    await w.on_track_end(g, None)
    check("R6 語音還在時照舊處理，不救援", not st.recovering and not st.queue)

    # 3) 語音被踢但閘道一直很健康（人踢的）：不救援
    g = Guild(); w = make(g, drop_ago=params.RECOVER_WINDOW + 5); st = w.state(1)
    st.current, st.started_at, st.queue = t, time.monotonic() - 10, deque()
    await w.on_track_end(g, None)
    check("R7 閘道沒出事時被踢（人踢的）：不自動回去", not st.recovering and not st.queue)

    # 4) 頻道沒人：一直等，有人回來才進
    g = Guild(humans=0); w = make(g, drop_ago=5); st = w.state(1); st.last_voice_id = 7
    st.current, st.started_at, st.queue = t, time.monotonic() - 5, deque()
    await w.on_track_end(g, None)
    async def people_back():
        await REAL_SLEEP(0.05); g.channel.members = [SimpleNamespace(bot=False)]
    with mock.patch.object(asyncio, "sleep", fast_sleep):
        await asyncio.gather(w._recover_tasks[1], people_back())
    check("R8 頻道沒人先等，有人回來才進頻道", g.voice_client is not None and w._played)

    # 5) 救援途中使用者 stop：放棄，不再進頻道
    g = Guild(); w = make(g, drop_ago=5); st = w.state(1); st.last_voice_id = 7
    st.current, st.started_at, st.queue = t, time.monotonic() - 5, deque()
    await w.on_track_end(g, None)
    task = w._recover_tasks[1]
    await w.stop(g)
    with mock.patch.object(asyncio, "sleep", fast_sleep):
        await task
    check("R9 救援中 stop：清掉進度、不進頻道", g.voice_client is None and not st.recovering and st.start_offset == 0.0)

    # 10) 網路瞬斷後語音物件還在但連不上：強制斷開再回頻道，之後才能播 / voice object left there but not connected after a blip: force disconnect, rejoin, then play
    class StuckVC(SimpleNamespace):
        def is_connected(self): return False
        def is_playing(self): return False
        def is_paused(self): return False
        async def disconnect(self, force=False): self.gone = True; self.guild.voice_client = None
    g = Guild(); w = make(g, drop_ago=999); st = w.state(1); st.last_voice_id = 7
    w.ensure_playing = PlayerBot.ensure_playing.__get__(w); w.repair_voice = PlayerBot.repair_voice.__get__(w)
    vc = StuckVC(channel=g.channel, guild=g); g.voice_client = vc
    async def fixed_ensure(g_, channel=None):
        g_.voice_client = SimpleNamespace(channel=g_.channel, is_connected=lambda: True); w._connected.append(1); return g_.voice_client
    w.ensure_voice = fixed_ensure
    ok = await w.repair_voice(g)
    check("R10 語音卡住：強制斷開並重連成功", ok and getattr(vc, "gone", False) and g.voice_client.is_connected() and w._connected, (ok, w._connected))
    ok2 = await w.repair_voice(g)
    check("R11 已經連著就什麼都不做", ok2 and len(w._connected) == 1)
    g = Guild(); w = make(g, drop_ago=999); st = w.state(1); st.last_voice_id = 7
    w.repair_voice = PlayerBot.repair_voice.__get__(w)
    g.voice_client = StuckVC(channel=g.channel, guild=g)
    async def failing(g_, channel=None): raise asyncio.TimeoutError()
    w.ensure_voice = failing
    check("R12 重連失敗不會丟例外，回傳 False（下一輪再試）", await w.repair_voice(g) is False)
    # 閒置檢查：卡住超過 VOICE_STALE_SECONDS 才動手 / the idle round acts only after VOICE_STALE_SECONDS
    g = Guild(); w = make(g, drop_ago=999); st = w.state(1); st.last_voice_id = 7
    calls = []
    async def fake_repair(g_): calls.append(1); return False
    w.repair_voice = fake_repair
    g.voice_client = StuckVC(channel=g.channel, guild=g)
    with mock.patch.object(PlayerBot, "guilds", new_callable=mock.PropertyMock, return_value=[g]):
        await w._idle_round()
    check("R13 剛斷線的第一輪先不動（給 discord.py 自己恢復的機會）", not calls and st.stale_since > 0)
    st.stale_since -= params.VOICE_STALE_SECONDS + 1
    with mock.patch.object(PlayerBot, "guilds", new_callable=mock.PropertyMock, return_value=[g]):
        await w._idle_round()
    check("R14 卡太久：閒置檢查會叫重連", calls == [1], calls)

asyncio.run(main())
print(f"{sum(res)}/{len(res)} 通過", flush=True)
sys.exit(0 if all(res) else 1)
