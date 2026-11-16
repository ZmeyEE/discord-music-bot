"""找專案資料夾、記住位置、算出看板網址

Finding the project folder, remembering it, and working out the dashboard URL.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from tkinter import filedialog, messagebox

APP_TITLE = "Discord 音樂機器人"


def app_dir() -> Path:
    """這個程式所在的資料夾（exe 或 .py 旁邊）/ The folder this program lives in (next to the exe or the .py)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent   # launcher/


def user_config_path() -> Path:
    r"""記住專案位置的設定檔（每個 Windows 使用者各自一份）/ The config file that remembers the project location (one per Windows user)."""
    return Path(os.environ.get("APPDATA") or Path.home()) / "MusicBotLauncher" / "launcher.json"


def find_project() -> Path | None:
    """依序找專案資料夾（順序寫在 launcher.py 最上面）；找不到回傳 None

    Look for the project folder in the order described at the top of launcher.py; returns None if not found.
    """
    cands: list[str] = [os.environ.get("MUSICBOT_DIR", "")]
    for cfg in (app_dir() / "launcher.json", user_config_path()):
        if cfg.exists():
            try:
                cands.append(json.loads(cfg.read_text(encoding="utf-8-sig")).get("project", ""))
            except (OSError, ValueError):
                pass
    if getattr(sys, "frozen", False):
        cands += [str(app_dir()), str(app_dir().parent)]
        cands += sibling_projects(app_dir().parent)
    else:
        cands.append(str(app_dir().parent))
    for c in cands:
        if c and (Path(c) / "bot.py").exists():
            return Path(c)
    return None


def sibling_projects(parent: Path) -> list[str]:
    """exe 放在專案旁邊（同一層）時，在隔壁找：有 bot.py 又有 musicbot/ 資料夾的才算，剛好只有一個才用

    When the exe sits next to the project (same parent folder): look at the siblings. Only a folder with bot.py and a musicbot/
    folder counts, and it is used only when there is exactly one such folder.
    """
    try:
        found = [str(p) for p in parent.iterdir() if p.is_dir() and (p / "bot.py").exists() and (p / "musicbot").is_dir()]
    except OSError:
        return []
    return found if len(found) == 1 else []


def remember_project(project: Path) -> None:
    """把使用者選的專案資料夾存起來，下次不用再選 / Save the folder the user picked so we don't ask again."""
    path = user_config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"project": str(project)}, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def ask_project() -> Path | None:
    """跳出資料夾選擇視窗，直到選到含 bot.py 的資料夾或使用者取消

    Show a folder picker until the user chooses a folder containing bot.py, or cancels.
    """
    while True:
        picked = filedialog.askdirectory(title="請選擇機器人專案資料夾（裡面要有 bot.py）/ Select the bot project folder (must contain bot.py)")
        if not picked:
            return None
        if (Path(picked) / "bot.py").exists():
            remember_project(Path(picked))
            return Path(picked)
        messagebox.showerror(APP_TITLE, "這個資料夾裡沒有 bot.py，請再選一次。\nNo bot.py in that folder, please try again.")


def dashboard_url(project: Path) -> str:
    """從 .env 的 RELAY_URL 推出看板網址（ws:// → http://）；沒有就用本地

    Work out the dashboard URL from ``RELAY_URL`` in .env (ws:// -> http://); falls back to localhost.
    """
    try:
        for line in (project / ".env").read_text(encoding="utf-8-sig").splitlines():
            if line.startswith("RELAY_URL="):
                u = line.split("=", 1)[1].strip().strip("\"'")
                if u:
                    return u.replace("wss://", "https://", 1).replace("ws://", "http://", 1)
    except OSError:
        pass
    return "http://127.0.0.1:8765"
