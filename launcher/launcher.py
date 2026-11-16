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
import tkinter as tk
from tkinter import messagebox

from botpanel.paths import APP_TITLE, ask_project, find_project
from botpanel.procs import single_instance
from botpanel.window import App


def main() -> None:
    """建立視窗並進入主迴圈 / Create the window and enter the main loop."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)   # 高 DPI 螢幕上文字才不會模糊 / keeps text sharp on high-DPI screens
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    if not single_instance():
        root.withdraw()
        messagebox.showinfo(APP_TITLE, "控制面板已經開著了。\nThe control panel is already open.")
        return
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
