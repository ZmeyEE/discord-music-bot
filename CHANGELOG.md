# Changelog / 更新紀錄

格式參考 [Keep a Changelog](https://keepachangelog.com/)，版本號遵循 [SemVer](https://semver.org/lang/zh-TW/)
Format follows [Keep a Changelog](https://keepachangelog.com/), versions follow [SemVer](https://semver.org/)

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
