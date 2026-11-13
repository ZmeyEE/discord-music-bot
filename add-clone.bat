@echo off
chcp 65001 >nul
rem ====================================================================
rem  Add one clone bot: it asks for the new bot's token and writes it to .env.
rem  新增一個分身：會請你貼上新機器人的 Token，並寫進 .env
rem  Details / 說明: README, section "clones" / "分身"
rem ====================================================================
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo 找不到 .venv，請先執行 start.bat 完成安裝。
  pause
  exit /b 1
)
.venv\Scripts\python.exe -X utf8 -m musicbot.addclone
echo.
pause
