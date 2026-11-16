"""機器人控制面板：用按鈕啟動／停止 Discord 音樂機器人，並顯示即時紀錄

只是"遙控器"：真正的機器人仍是專案裡的 bot.py（由 .venv 的 Python 執行）

專案資料夾位置依序從這些地方找（找到第一個含 bot.py 的就用）：
  1. 環境變數 MUSICBOT_DIR
  2. launcher.json（放在 exe 旁邊，或 %APPDATA%\\MusicBotLauncher\\）：{"project": "專案資料夾路徑"}
  3. 以原始碼執行時：launcher/ 的上一層；打包成 exe 時：exe 所在資料夾或它的上一層
  4. 都找不到 -> 跳出視窗請你選擇資料夾，並記住（寫進 %APPDATA%\\MusicBotLauncher\\launcher.json）

各零件在 launcher/botpanel/：paths.py（專案位置）、procs.py（啟動／停止機器人）、theme.py（配色，同網頁看板）、
widgets.py（畫面零件）、window.py（視窗）

Bot control panel: start / stop the Discord music bot with buttons and watch the live log.

It is only a "remote control": the real bot is still ``bot.py`` in the project (run with the .venv's Python).

The project folder is searched in this order (the first one containing bot.py wins):
  1. the ``MUSICBOT_DIR`` environment variable
  2. ``launcher.json`` (next to the exe, or in ``%APPDATA%\\MusicBotLauncher\\``): {"project": "path to the project"}
  3. running from source: the parent of ``launcher/``; packaged exe: the exe's folder or its parent
  4. nothing found -> a folder picker asks you, and the answer is remembered
     (saved to ``%APPDATA%\\MusicBotLauncher\\launcher.json``)

The parts live in launcher/botpanel/: paths.py (project location), procs.py (start / stop the bot), theme.py (colours,
as the web dashboard), widgets.py (UI parts), window.py (the window).

Build the exe / 打包成 exe:
  pip install pyinstaller
  pyinstaller --onefile --windowed --icon launcher/MusicBotLauncher.ico --name MusicBotLauncher launcher/launcher.py
圖示是 launcher/MusicBotLauncher.ico，想換就換掉這個檔案 / the icon is launcher/MusicBotLauncher.ico, replace that file to change it
"""
from __future__ import annotations

import ctypes
import time
import tkinter as tk
from tkinter import messagebox

from botpanel.paths import APP_TITLE, ask_project, find_project
from botpanel.procs import focus_existing, kill_tree, other_panels, single_instance
from botpanel.window import App


def already_open() -> bool:
    """已經有一個控制面板了：先把它的視窗叫到最前面；找不到視窗卻還有舊程序卡在背景，就問要不要關掉它。回傳 True 表示可以接著開新的

    A panel is already open: bring its window to the front first. If there is no window but an old process still hangs in
    the background, ask whether to close it. Returns True when a new window may be opened.
    """
    if focus_existing(APP_TITLE):
        return False
    stale = other_panels()
    if not stale:
        messagebox.showinfo(APP_TITLE, "控制面板已經開著了。\nThe control panel is already open.")
        return False
    if not messagebox.askyesno(APP_TITLE, "控制面板已經在背景執行，但找不到它的視窗。\n要關掉舊的、開一個新的嗎？\n\nAn old panel is running without a window. Close it and open a new one?"):
        return False
    for pid in stale:
        kill_tree(pid)
    time.sleep(1.0)
    return single_instance()


def main() -> None:
    """建立視窗並進入主迴圈 / Create the window and enter the main loop."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)   # 高 DPI 螢幕上文字才不會模糊 / keeps text sharp on high-DPI screens
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    if not single_instance():
        root.withdraw()
        if not already_open():
            return
        root.deiconify()   # 舊的關掉後，這個視窗才要顯示 / the old one is gone, so this window may show now
    project = find_project()
    if project is None:
        root.withdraw()
        project = ask_project()
        if project is None:
            return
        root.deiconify()
    App(root, project)
    root.mainloop()


if __name__ == "__main__":
    main()
