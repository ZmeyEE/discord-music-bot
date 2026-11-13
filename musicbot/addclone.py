"""新增一個分身：貼上新機器人的 Token → 驗證 → 寫進 .env → 印出邀請連結

用法：add-clone.bat（Windows）或 python -m musicbot.addclone
Token 用隱藏輸入，不會顯示在畫面上，也不會被印出來或寫進記錄

Add one clone bot: paste the new bot's token -> validate it -> append it to .env -> print an invite link.

Usage: add-clone.bat (Windows) or ``python -m musicbot.addclone``.
The token is read with hidden input, so it is never echoed, printed or logged.
Why clones? Discord allows one voice channel per bot per server, so playing in several channels at
once needs several bot accounts. Discord does not let programs create bot accounts for you.
"""
from __future__ import annotations

import getpass
import json
import os
import re
import sys
import urllib.error
import urllib.request

from . import config
from .commands import invite_url
from .paths import ENV_FILE

API_ME = "https://discord.com/api/v10/users/@me"  # 查詢"這個 Token 是誰"的 Discord API / Discord endpoint that tells who a token belongs to


def check_token(token: str) -> dict:
    """向 Discord 確認這個 Token 有效，回傳該機器人的資料（id、名稱）

    Ask Discord whether the token is valid; returns the bot's profile (id, username...).
    Raises ``urllib.error.HTTPError`` (e.g. 401) when the token is rejected.
    """
    req = urllib.request.Request(API_ME, headers={"Authorization": f"Bot {token}", "User-Agent": "DiscordBot (musicbot-addclone, 1.0)"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def next_slot(env_text: str) -> int:
    """下一個可用的 DISCORD_TOKEN_n 編號（從 2 開始）

    The next free ``DISCORD_TOKEN_n`` number in an .env text (the main bot is slot 1, clones start at 2).
    """
    used = [int(m.group(1)) for m in re.finditer(r"(?m)^\s*DISCORD_TOKEN_(\d+)\s*=", env_text)]
    return max([1, *used]) + 1


def main() -> int:
    """互動式流程，回傳 0 表示成功，1 表示取消或失敗

    Interactive flow. Returns 0 on success, 1 when cancelled or failed.
    """
    config.load_env()
    print("新增分身：每個分身是一個獨立的 Discord 機器人帳號（Discord 的規定，沒辦法用程式代替你建立）。")
    print("還沒有的話，到 https://discord.com/developers/applications → New Application → Bot → Reset Token，複製 Token。\n")
    token = getpass.getpass("貼上新機器人的 Token（輸入時不會顯示，貼完按 Enter）：").strip().strip('"').strip("'")
    if not token:
        print("沒有輸入，已取消。")
        return 1
    if token in config.discord_tokens():
        print("這個 Token 已經在使用中了，不需要再新增。")
        return 1
    # --- 驗證 Token / validate the token ---
    try:
        me = check_token(token)
    except urllib.error.HTTPError as exc:
        print("Discord 說這個 Token 無效" + ("（401）。請確認有複製完整、沒有多餘的空白。" if exc.code == 401 else f"（HTTP {exc.code}）。"))
        return 1
    except (urllib.error.URLError, OSError) as exc:
        print(f"連不上 Discord，沒有新增：{exc}")
        return 1
    if not me.get("bot"):
        print("這個 Token 不是機器人的 Token，沒有新增。")
        return 1

    # --- 寫進 .env / append to .env ---
    text = ENV_FILE.read_text(encoding="utf-8-sig") if ENV_FILE.exists() else ""
    slot = next_slot(text)
    sep = "" if (not text or text.endswith("\n")) else "\n"   # 前一行沒換行就先補一個 / add a newline first if the file lacks one
    with open(ENV_FILE, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(f"{sep}DISCORD_TOKEN_{slot}={token}\n")
    try:
        os.chmod(ENV_FILE, 0o600)   # 只有擁有者可讀寫（Windows 上多半無效，但無害）/ owner-only permissions (mostly a no-op on Windows)
    except OSError:
        pass

    # --- 告訴使用者下一步 / tell the user what to do next ---
    print(f"\n已新增分身「{me.get('username')}」，寫入 .env 的 DISCORD_TOKEN_{slot}。")
    print("下一步：")
    print(f"  1. 用這個連結把它邀請到你的伺服器（分身只需要這一個連結）：\n     {invite_url(int(me['id']), with_commands=False)}")
    print("  2. 重新啟動機器人（關掉再開一次 start.bat）。")
    print("  3. 在 Discord 輸入 /players，可以看到所有分身的狀態。")
    print("\n分身沒有數量上限；撐不住時，卡頓偵測器會自動從最後加入的頻道開始逐個停止。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
