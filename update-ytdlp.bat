@echo off
chcp 65001 >nul
rem ====================================================================
rem  Update yt-dlp. Video sites change often; if searching or playing suddenly fails, run this first.
rem  更新 yt-dlp，影音網站常改版，搜尋或播放突然失敗時，先跑這個
rem ====================================================================
cd /d "%~dp0"
".venv\Scripts\python.exe" -m pip install -U yt-dlp
pause
