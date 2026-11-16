# Changelog / 更新紀錄

格式參考 [Keep a Changelog](https://keepachangelog.com/)，版本號遵循 [SemVer](https://semver.org/lang/zh-TW/)
Format follows [Keep a Changelog](https://keepachangelog.com/), versions follow [SemVer](https://semver.org/)

## [1.2.0] - 2026-11-16

### 修正 / Fixes
- 大清單很卡：原本每次狀態一變就把整份清單（1000 張卡片 287 KB）重送給每個瀏覽器，現在一開始只送 100 首、往下捲再載入（最多 1000），清單沒變就不重送；5000 首時 20 次通知從 5.7 MB 降到 33 KB，網頁節點從 22,222 個降到 2,422 個 / large queues were laggy: every state change re-sent the whole list (1000 cards, 287 KB) to every browser. Now 100 songs are sent at first, scrolling loads more (up to 1000) and an unchanged list is not sent again; with 5000 songs, 20 notifications went from 5.7 MB to 33 KB and the page from 22,222 DOM nodes to 2,422
- 手機寬度的版面：面板被壓扁、互相重疊、會左右捲，現在三欄疊成一欄、整頁往下捲 / phone-width layout: panels were squashed, overlapped and scrolled sideways; now the three columns stack and the whole page scrolls
- `.env` 裡的 `MAX_QUEUE`、`EMPTY_LEAVE_SECONDS`、`IDLE_LEAVE_SECONDS` 之前沒有生效（參數在 `.env` 讀進來之前就定下來了）/ `MAX_QUEUE`, `EMPTY_LEAVE_SECONDS` and `IDLE_LEAVE_SECONDS` in `.env` had no effect (the parameters were fixed before `.env` was read)
- 控制面板修正：游標停在按鈕上會凍住（現在按鈕用座標判斷滑鼠，不再自己觸發自己）、重複開啟會把已開著的視窗叫到最前面、找不到視窗的舊程序（包含不同檔名的 exe）會問要不要關掉、關視窗時外部啟動的機器人會先問、停止在背景做不卡視窗、exe 放在專案隔壁時自己找得到專案 / control panel fixes: the freeze when the pointer rests on a button (buttons are now hit-tested by coordinates, so they no longer trigger themselves), a second launch brings the open window forward, an old process with no window (even an exe with another name) is offered to be closed, closing asks about a bot started elsewhere, stopping runs in the background, and the project is found when the exe sits next to it
- 控制面板 exe 檔名帶版本（`MusicBotLauncher-1.1.0.exe`），版本也寫進檔案版本資訊，視窗標題旁顯示 v1.1.0；用 `python launcher/build.py` 打包 / the exe file name carries the version (`MusicBotLauncher-1.1.0.exe`), the version is also in the file version info and shown next to the window title; build with `python launcher/build.py`

### 變更 / Changed
- 預設不打擾頻道裡的其他人：指令回覆只有下指令的人看得到，機器人只在出問題時才在頻道發訊息（不再每首歌發"正在播放"）；要回到原本的樣子，在 `.env` 設 `PUBLIC_REPLIES=1` 和 `CHANNEL_NOTICES=all` / by default other people in the channel are not disturbed: command replies are visible to the caller only and the bot posts in a channel only when something went wrong (no more "now playing" for every song); set `PUBLIC_REPLIES=1` and `CHANNEL_NOTICES=all` in `.env` for the old behaviour

## [1.1.0] - 2026-11-16

### 新增 / Added
- Spotify 連結（單曲、專輯、播放清單）：讀歌名和歌手，去 Bilibili（不行換 YouTube）找對應的歌，播放清單最多讀到 100 首 / Spotify links (track, album, playlist): read title and artists, match the song on Bilibili (YouTube as a fallback), playlists are read up to 100 songs
- 合集一次最多 5000 首（原本 50），一個伺服器的待播清單最多 5000 首（`MAX_QUEUE`）/ a playlist adds up to 5000 songs at once (was 50), one server's queue holds up to 5000 (`MAX_QUEUE`)
- 看板多語言：繁中（預設）、簡中、English、日本語，右上角選單，底下小標 Language / dashboard languages: Traditional Chinese (default), Simplified Chinese, English, Japanese, menu at the top right with a small "Language" caption
- Windows 效能調整：優先權高一級、關掉省電降速、1 ms 計時（`TUNE_PROCESS=0` 關閉）/ Windows tuning: priority one step up, no power throttling, 1 ms timer (`TUNE_PROCESS=0` to skip)

### 變更 / Changed
- 看板一次最多畫前 1000 張待播卡片（5000 首全送一次要 1.7 MB），總數另外顯示 / the dashboard draws at most the first 1000 queued cards (all 5000 would be 1.7 MB per update), the total is shown separately
- 補縮圖改成先補前 50 首，之後播到哪補到哪，不再一次打幾千次站方 / thumbnails are filled for the first 50, then as songs get close, instead of thousands of requests at once
- PyNaCl 升到 1.6.2（修掉 pip-audit 的 2 個已知漏洞），不再用 `discord.py[voice]`，因為它把 PyNaCl 鎖在 `<1.6` / PyNaCl 1.6.2 (fixes the 2 known issues pip-audit reported), `discord.py[voice]` is no longer used because it pins PyNaCl `<1.6`

### 重構 / Refactor
- 全部參數集中到 `musicbot/params.py`，其他檔案只讀 `params.名稱` / every tunable parameter now lives in `musicbot/params.py`, other files only read `params.NAME`
- 長檔案依功能拆開：`player/`、`hub/`、`sources/`、`health/`、`relay/`、`dashboard/`、`commands/`、`app.py` 拆出 `tuning.py` 與 `logging_setup.py`，最長的檔案約 210 行 / long files are split by feature, the longest file is about 210 lines
- 網頁 `app.js`（1168 行）拆成 `web/js/` 的 16 個 ES 模組，最長 137 行 / the 1168-line `app.js` is split into 16 ES modules in `web/js/`, the longest is 137 lines
- 桌面小視窗（`launcher/`）重建：配色、膠囊按鈕、半透明卡片和狀態燈都跟網頁看板一致，程式拆成 `launcher/botpanel/` 的 7 個小檔（最長 155 行），啟動／停止的邏輯不碰畫面，新增 `tests/launcher_unit.py`（23 項）/ the desktop window (`launcher/`) is rebuilt: colours, pill buttons, frosted cards and the status light match the dashboard; the code is split into 7 small files in `launcher/botpanel/` (the longest is 155 lines), the start / stop logic never touches the UI, and `tests/launcher_unit.py` (23 checks) is new
- 行為沒有改：測試全過，網頁用瀏覽器實際操作過一遍（加歌、暫停、跳轉、分頁選單、刪除、換語言）/ no behavior change: all tests pass and the dashboard was driven in a real browser (add, pause, seek, tab menu, remove, switch language)

### 實測 / Measured
- i5-12400F 上 120 個頻道同時送包：Python 約 30% 單核，沒有任何包遲到超過 40 ms / 120 simultaneous channels on an i5-12400F: Python about 30% of one core, no packet later than 40 ms
- 同時播放的頻道數就是 bot 帳號數，沒有人為上限，要更多頻道就加分身 / the number of simultaneous channels equals the number of bot accounts, there is no artificial cap, add clones for more

## [1.0.1] - 2026-11-14

### 修正 / Fixes
- Discord 閘道斷線後，bot 要睡很久才重連（最長約 17 分鐘），現在上限 16 秒 / after a Discord gateway outage bots slept up to ~17 min before reconnecting, now capped at 16 s
- 斷線時語音被踢掉（4014），播到一半的歌會丟掉，也不會回頻道，現在連線恢復後自己回去、從原本的秒數接著播 / a voice kick (4014) during an outage dropped the song and left the bot out of the channel, now it rejoins and resumes from the same second
- 人手動踢掉 bot 不會觸發自動回去 / a manual kick by a person does not trigger the auto-rejoin
- 新增 `tests/recover_unit.py` / added `tests/recover_unit.py`

## [1.0.0] - 2026-11-14

第一個公開版本 / first public release

### 功能 / Features
- Bilibili 優先：貼網址、BV 號、分享文字或關鍵字，也支援 YouTube 等 yt-dlp 能解析的網站 / Bilibili first: URL, BV id, share text or keywords; YouTube and other yt-dlp sites work too
- 取最高品質音軌，轉 Opus（預設 192，最高 510 kbps），看板上可即時切換音質 / best audio track re-encoded to Opus (192 default, up to 510 kbps), switchable live on the dashboard
- 卡片式網頁看板：拖曳排序、拖到右側刪除、進度條、單曲／列表循環、與 Discord 即時同步 / card-style dashboard: drag to reorder, drag to the trash, seek bar, single / queue loop, live sync with Discord
- 分身：同一個伺服器多頻道同時播放，卡頓偵測器確定原因後從最後加入的頻道開始停止 / clones: several channels of one server at once, the stutter detector stops the newest channel first once it is sure of the cause
- 三種看板權限：`open`、`verify`（/help 專屬連結、裝置只存雜湊）、`voice` / three dashboard access modes: `open`, `verify` (personal /help link, devices stored as hashes), `voice`
- 選用中繼站（VPS／樹莓派）：讓朋友連看板，音樂仍在家裡播，家裡不用開任何埠 / optional relay (VPS / Raspberry Pi): friends reach the dashboard while the music keeps playing at home, no home port needed
- Bilibili 掃碼登入（大會員可用無損音源，此路徑尚未實測）/ Bilibili QR login (premium accounts unlock lossless audio, this path is not tested yet)
- 桌面啟動／關閉小視窗（選用，tkinter）/ tiny desktop start / stop window (optional, tkinter)

### 專案 / Project
- 全專案中英雙語註解，開發者指南見 [docs/](docs/) / bilingual comments everywhere, developer guides in [docs/](docs/)
- 回歸測試放在 [tests/](tests/)（Discord 語音層用假的）/ regression tests in [tests/](tests/) (fake Discord voice layer)
- Unlicense 授權，第三方元件見 [THIRD_PARTY.md](THIRD_PARTY.md) / Unlicense, third-party list in [THIRD_PARTY.md](THIRD_PARTY.md)

### 已知限制 / Known limits
- 還沒有 i18n 機制，文字寫在程式裡（繁體中文）/ no i18n layer yet, texts are in the code (Traditional Chinese)
- 主要在 Windows 上開發與測試 / developed and tested mainly on Windows
- 需要自備 ffmpeg 與機器人 Token / you bring your own ffmpeg and bot token
- 測試需要網路（會解析一支 Bilibili 影片）/ the tests need network access (they resolve one Bilibili video)
- 長時間穩定性還需要更多實際使用的觀察 / long-run stability needs more real-world use
