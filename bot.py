"""本地執行、完全 free 的高音質 Discord 音樂 bot 進入點，實作都在 musicbot/ 套件裡

Entry point of the free, high-quality Discord music bot that runs on your own PC. All the real work lives in the
``musicbot/`` package; this file only calls ``musicbot.app.main()``.

Run it with:  python bot.py   (or double-click start.bat on Windows)
"""
from musicbot.app import main

if __name__ == "__main__":
    main()
