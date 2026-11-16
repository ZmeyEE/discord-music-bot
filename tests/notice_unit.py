"""不打擾別人的單元測試（不需要 Discord、不連網）：頻道訊息的開關、指令回覆只有本人看得到、.env 套用到參數
Unit tests for "don't disturb others" (no Discord, no network): the channel-notice switch, replies visible to the caller only, .env applied to params

用 tests/run_all.py 執行 / run it with tests/run_all.py
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 專案根目錄 / project root
sys.path.insert(0, ROOT)
from musicbot import config, params
from musicbot.commands.helpers import Helpers
from musicbot.player import GuildState, PlayerBot

res = []
def check(n, ok, d=""): res.append(bool(ok)); print(("PASS" if ok else "FAIL"), n, str(d)[:190], flush=True)

# ============ 預設值 ============
check("D1 預設：指令回覆只有本人看得到、頻道只發問題", params.PUBLIC_REPLIES == 0 and params.CHANNEL_NOTICES == "problems", (params.PUBLIC_REPLIES, params.CHANNEL_NOTICES))

# ============ 哪些訊息可以發 ============
table = {}
for level in params.NOTICE_LEVELS:
    with mock.patch.object(params, "CHANNEL_NOTICES", level):
        table[level] = (params.notices_allow(False), params.notices_allow(True))
check("N1 all：一般訊息和問題都發", table["all"] == (True, True), table)
check("N2 problems：只發問題", table["problems"] == (False, True), table)
check("N3 off：都不發", table["off"] == (False, False), table)

# ============ .env 套用到參數 ============
saved = {k: getattr(params, k) for k in (*params.ENV_INTS, "CHANNEL_NOTICES")}
env_keys = (*params.ENV_INTS, "CHANNEL_NOTICES")
old_env = {k: os.environ.pop(k, None) for k in env_keys}
try:
    env_file = Path(tempfile.mkdtemp(prefix="notice_test_")) / ".env"
    env_file.write_text("MAX_QUEUE=123\nEMPTY_LEAVE_SECONDS=7\nPUBLIC_REPLIES=1\nCHANNEL_NOTICES=OFF\n", encoding="utf-8")
    with mock.patch.object(config, "ENV_FILE", env_file):
        config.load_env()
    check("E1 .env 的值套用到參數（舊版在 .env 讀進來之前就定下來了，所以沒生效）",
          (params.MAX_QUEUE, params.EMPTY_LEAVE_SECONDS, params.PUBLIC_REPLIES, params.CHANNEL_NOTICES) == (123, 7, 1, "off"),
          (params.MAX_QUEUE, params.EMPTY_LEAVE_SECONDS, params.PUBLIC_REPLIES, params.CHANNEL_NOTICES))
    os.environ["MAX_QUEUE"] = "abc"; os.environ["CHANNEL_NOTICES"] = "loud"
    params.apply_env()
    check("E2 格式不對的值維持原樣", params.MAX_QUEUE == 123 and params.CHANNEL_NOTICES == "off", (params.MAX_QUEUE, params.CHANNEL_NOTICES))
finally:
    for k in env_keys:
        os.environ.pop(k, None)
        if old_env[k] is not None:
            os.environ[k] = old_env[k]
    for k, v in saved.items():
        setattr(params, k, v)
check("E3 測試後參數還原", params.MAX_QUEUE == saved["MAX_QUEUE"] and params.CHANNEL_NOTICES == saved["CHANNEL_NOTICES"])


# ============ 機器人主動發的頻道訊息 ============
def make_bot(sent):
    w = PlayerBot.__new__(PlayerBot)
    async def send(text): sent.append(text)
    w.get_channel = lambda cid: SimpleNamespace(send=send)
    return w


async def channel_notices():
    for level, want in (("problems", ["壞了"]), ("all", ["正在播放", "壞了"]), ("off", [])):
        sent = []
        w = make_bot(sent)
        st = GuildState(); st.text_channel_id = 1
        with mock.patch.object(params, "CHANNEL_NOTICES", level):
            await w._say(st, "正在播放")
            await w._say(st, "壞了", problem=True)
        check(f"C {level}：頻道收到 {want}", sent == want, sent)

    # 指令回覆 / command replies
    calls = []
    class Response:
        def __init__(self): self.done = False
        def is_done(self): return self.done
        async def send_message(self, **kw): calls.append(("first", kw["ephemeral"])); self.done = True
    class Followup:
        async def send(self, **kw): calls.append(("followup", kw["ephemeral"]))
    h = Helpers(SimpleNamespace())
    it = SimpleNamespace(response=Response(), followup=Followup())
    await h.say(it, "已跳過", ephemeral=False)
    await h.say(it, "第二則", ephemeral=False)
    check("R1 預設：要求公開的回覆也只有本人看得到（第一則和後續都是）", calls == [("first", True), ("followup", True)], calls)
    calls.clear()
    with mock.patch.object(params, "PUBLIC_REPLIES", 1):
        it = SimpleNamespace(response=Response(), followup=Followup())
        await h.say(it, "已跳過", ephemeral=False)
        await h.say(it, "請先加入語音頻道", ephemeral=True)
    check("R2 PUBLIC_REPLIES=1：照原本的，公開的公開、私下的私下", calls == [("first", False), ("followup", True)], calls)

asyncio.run(channel_notices())
print(f"{sum(res)}/{len(res)} 通過", flush=True)
sys.exit(0 if all(res) else 1)
