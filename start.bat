@echo off
chcp 65001 >nul
rem ====================================================================
rem  Start the Discord music bot.  啟動 Discord 音樂機器人
rem  Double-click this file, or run  .\start.bat  in a terminal.
rem  雙擊這個檔案，或在終端機執行  .\start.bat 
rem  Note: typing only  start.bat  in cmd fails because start is a built-in command.
rem  注意：在 cmd 只打 start.bat 會失敗（start 是內建指令），請加上 .\ 
rem  Close this window to stop the bot.  關掉這個視窗就會停止機器人
rem ====================================================================
cd /d "%~dp0"
title Discord Music Bot
rem Check that the virtual environment exists.  檢查虛擬環境是否存在
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] .venv not found. See README.md to create the virtual environment.
  pause
  exit /b 1
)
echo Starting bot... (close this window to stop it)
rem -X utf8 makes Python use UTF-8 for text.  -X utf8 讓 Python 一律用 UTF-8
".venv\Scripts\python.exe" -X utf8 bot.py
echo.
echo Bot stopped. Exit code: %errorlevel%
pause
