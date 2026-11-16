"""機器人控制面板的各個零件 / The parts of the bot control panel

版本號只寫在這裡：視窗標題旁、exe 檔名（MusicBotLauncher-1.1.0.exe）、exe 的檔案版本資訊都用它，改版請和 musicbot 的版本一起改
The version lives only here: next to the window title, in the exe file name (MusicBotLauncher-1.1.0.exe) and in the exe's file
version info. Bump it together with the musicbot version.

  paths.py    找專案資料夾、看板網址 / project folder, dashboard URL
  procs.py    程序控制：啟動／停止機器人（不碰畫面）/ process control: start and stop the bot (no UI)
  theme.py    配色與字體，同網頁看板 / colours and fonts, as the web dashboard
  widgets.py  畫面零件：漸層背景、卡片、膠囊按鈕、狀態燈 / UI parts: gradient, cards, pill buttons, status light
  window.py   視窗本體 / the window
"""
__version__ = "1.1.0"
