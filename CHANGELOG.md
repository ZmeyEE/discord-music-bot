# Changelog / 更新紀錄

格式參考 [Keep a Changelog](https://keepachangelog.com/)，版本號遵循 [SemVer](https://semver.org/lang/zh-TW/)
Format follows [Keep a Changelog](https://keepachangelog.com/), versions follow [SemVer](https://semver.org/)

## [2.1.0] - 2026-11-17

### 新增 / Added
- **我的歌單可以拖曳**：視窗左邊多了一排像檔案總管的資料夾列（點一下跳過去，只畫展開的資料夾）；卡片可以拖來排序、拖到左邊的資料夾列或上方路徑搬進資料夾、拖到右上角的刪除區刪除；歌單裡的歌曲同樣能排序、拖到資料夾列的另一張歌單、拖去刪除。選取模式下拖一張被選的就整批一起走。用的是待播清單同一個 SortableJS，手機寬度只隱藏左邊的列。/ The library dialog gets a file-explorer-like folder bar on the left, and cards and songs can be dragged: reorder, drop on the folder bar or a breadcrumb to move, drop on the trash at the top right to delete (several selected items move together). Same SortableJS as the queue; phone width only hides the bar.
- **Spotify 按鈕永遠顯示**：沒設定 `SPOTIFY_CLIENT_ID` 時按鈕不再藏起來，點開會寫怎麼設定 / The Spotify button is always shown; without `SPOTIFY_CLIENT_ID` it explains how to set it up.
- **Spotify 可以直接在看板上設定與登入**：擁有者在 Spotify 視窗貼上 Client ID 按儲存（存在 settings.json，`.env` 有設定時以 `.env` 為主），就能直接按"前往授權"登入，不必再改檔案重開機器人 / Spotify can be set up and logged in right on the dashboard: the owner pastes the Client ID in the Spotify dialog (kept in settings.json; `.env` wins when set) and can then authorise without editing files or restarting.
- **左邊資料夾列也能拖、也是放置點**：按住一列拖到另一列（中間 = 放進資料夾，上緣／下緣 = 插在那個位置）或刪除區；卡片放在列的上緣／下緣就會排到那個位置，停在另一張資料夾卡片中央就放進去 / the folder bar rows can be dragged and are drop points: middle of a row = move inside, top / bottom edge = insert at that spot; a card dropped on a row's edge lands there, and resting on the middle of another folder card puts it inside.
- 控制面板 exe 的圖示換成面板左上角的唱片 logo / the launcher exe icon is now the record-disc logo of the panel.

### 修正 / Fixes
- 我的歌單左邊資料夾列最上層"我的歌單"收不起來（每次重畫都被自動展開）/ the top level of the folder bar could not be collapsed (every redraw re-expanded it).
- 兩顆帳號按鈕（Spotify、Bilibili）之間隔很遠，現在貼在一起 / the two account buttons (Spotify, Bilibili) sat far apart; they are now together.
- 中繼站：某個瀏覽器剛好斷線時，轉送訊息丟出的例外會把家裡機器人的連線也弄斷（全體看到離線、約 3 秒後重連）/ relay: a browser that had just dropped made the forwarding raise and cut the home bot's connection for everyone.
- 卡頓保護：`CHANNEL_NOTICES=off`，或公告逾時（上傳頻寬滿了）時，沒有真的停掉最後加入的頻道 / stutter protection did not stop the last-joined channel when notices were off or the notice timed out.
- 開始播放失敗（ffmpeg 起不來、語音剛好斷線）時，那首歌不再憑空消失，放回待播最前面 / a song whose playback failed to start is put back at the front of the queue instead of vanishing.
- 存檔：`library.json`、`members.json`、`spotify_tokens.json`、`settings.json` 改成真正的原子寫入（fsync）；檔案壞掉（或最外層不是字典）時先改名備份成 `*.bad-時間` 再從空的開始，不再被下一次存檔直接蓋掉；`settings.json` 以前是直接覆寫 / persistence now fsyncs, keeps a broken file aside as `*.bad-<time>` instead of overwriting it, and `settings.json` is no longer written in place.
- 同一個人用連結重新整理會一直領新的裝置憑證（一個人累積 50 筆）：現在同一人同一伺服器最多記住 5 個（`DEVICE_MAX_PER_USER`），登記時順便清掉過期的 / refreshing a link kept issuing new device tokens; now capped per person per server and expired ones are purged.
- 跨資料夾循環遇到空資料夾會整個停掉，現在跳過空的、繞一圈都沒有歌才結束 / "loop across folders" stopped at an empty folder; it now skips empty ones.
- 歌單歌曲：移除後、列表更新前再點會刪到錯的歌（列是用編號指的），現在更新前鎖住；慢到的舊回覆不再接在新列表後面 / song rows are locked until the list refreshes after a change, and late stale replies are ignored.
- 其他：閒置離開的監看迴圈、中繼連線的訊息處理、分身啟動、控制面板記錄區，出一次錯就整個停擺 → 現在只記錄、繼續；暫停中按鍵盤右鍵進度跳太多；待播清單一下子縮短時畫面空白；一次搬上千首歌很慢 / one error no longer stops the idle watcher, the relay message loop, clone start-up or the launcher log view; keyboard seek while paused; blank queue after a sudden shrink; moving thousands of songs was slow.

### 測試 / Tests
- 新增 `library_drag.py`（無頭 Chrome 真滑鼠拖曳，24 項）、`persist_unit.py`（存檔與裝置登錄），`library_unit.py` 加了排序與搬歌 / new `library_drag.py` (real-mouse drags, 24 checks) and `persist_unit.py`; `library_unit.py` covers reordering and moving songs.

## [2.0.0] - 2026-11-17

### 重大變更 / Breaking
- **入口只剩 `/help` 的專屬連結**：移除"知道網址就能控制"的 `open` 模式（`DASHBOARD_ACCESS` 只剩 `verify`（預設）和 `voice`；舊 `.env` 寫 `open` 會自動當成 `verify` 並在記錄裡提醒）。中繼站不再公開伺服器清單。本機直接開 localhost 仍是主人 / **the personal link from `/help` is the only way in**: the `open` mode (knowing the URL was enough) is gone; `DASHBOARD_ACCESS` is now `verify` (default) or `voice`, an old `.env` saying `open` is treated as `verify` with a warning in the log. The relay no longer lists servers. Opening localhost on the bot's machine is still the owner

### 新增 / Added
- **我的歌單**：每位 Discord 使用者自己的資料夾與歌單（存連結，不存聲音，存在這台電腦的 `library.json`）。資料夾可以巢狀（最多 8 層）；多選待播歌曲存成歌單、多選歌單建立資料夾、改名、搬移、刪除；貼 Bilibili／YouTube／Spotify 連結直接存入；每張待播卡片右上角有"加入歌單"；開啟有動畫，卡片是歌單／資料夾樣式 / **My playlists**: each Discord user's own folders and playlists (links, not audio, stored in `library.json` on this machine). Folders nest (up to 8 levels); select queued songs to save a playlist, select playlists to make a folder, rename, move, delete; paste a Bilibili / YouTube / Spotify link to save it; every queued card has an "add to a playlist" button; opening has an animation and playlists / folders are cards
- **資料夾循環與跨資料夾循環**：播放資料夾時可選"播完重播這個資料夾"或"播完換同一層的下一個資料夾（到底繞回第一個）"；清空待播或停止就結束循環 / **folder loop and loop across folders**: playing a folder can replay it when it ends, or move on to the next folder on the same level (wrapping around); clearing the queue or stopping ends the loop
- **Spotify 帳號連結**（Bilibili 按鈕上方）：連結後可以列出自己的 Spotify 歌單並存進我的歌單；用授權碼 + PKCE（不需要 Client Secret），授權完把網址貼回看板，所以朋友經過中繼站也能用。需要 `.env` 的 `SPOTIFY_CLIENT_ID`。**限制**：Spotify 開發模式要擁有者有 Premium、最多 5 位使用者、只讀得到自己建立或共同編輯的歌單；**這部分只用假的 Spotify 回應測過，還沒有用真的 Premium 帳號驗證** / **Spotify account link** (above the Bilibili button): once linked, one's own Spotify playlists can be listed and saved into My playlists; authorisation code + PKCE (no client secret), and the address is pasted back into the dashboard so friends can use it through the relay. Needs `SPOTIFY_CLIENT_ID` in `.env`. **Limits**: Spotify Development Mode needs a Premium owner, allows 5 users and only reads playlists the user owns or collaborates on; **this was tested only with fake Spotify answers, not yet against a real Premium account**
- **音質**：來源本身是 Opus（YouTube）就原封不動送進 Discord（不重新編碼，逐位元相同）；Bilibili 的 AAC 重編時不再讓 discord.py 假設 15% 掉包（實測 256k 時波形相似度 16 dB → 24 dB），有 soxr 就用它轉 44.1→48 kHz；看板顯示"直通"或實際位元率 / **audio quality**: an Opus source (YouTube) goes into Discord untouched (bit-exact, no re-encoding); Bilibili's AAC is re-encoded without discord.py's assumed 15% packet loss (measured waveform similarity 16 dB → 24 dB at 256k) and with soxr when available for 44.1 → 48 kHz; the dashboard shows "direct" or the real bitrate
- **Spotify 歌曲找對應影片更準**：真的取串流看實際長度（過濾掉 42 分鐘的循環版）、比音質、記住挑到的影片；"你 - 鄭潤澤"以前挑到 68 kbps 的循環版，現在是 4:27 的 Opus 139 kbps / **better matching of Spotify songs to videos**: the true length is checked (a 42-minute loop version is filtered out), quality is compared and the pick is remembered; "你 - 鄭潤澤" used to land on a 68 kbps loop version and is now the 4:27 Opus 139 kbps one
- **虛擬清單**：待播清單只畫看得到的卡片，2500 張時捲動和拖曳排序都是 60 fps、刪除一張約 75 毫秒（以前 1000 張就會卡）；一個瀏覽器最多載入 5000 首，往下捲時每次載入量倍增 / **virtual list**: the queue draws only the cards in view; with 2500 cards scrolling and drag-reordering run at 60 fps and a delete takes about 75 ms (1000 cards used to lag); a browser may load up to 5000 songs and each load on scroll doubles

### 測試 / Tests
- 新增 `perf_ui.py`（無頭 Chrome 量 2500 張卡片的 fps）、`library_ui.py`（歌單介面，含假 Spotify）、`library_test.py`、`library_unit.py`、`spotify_unit.py`、`audio_unit.py`、`link_test.py`（取代 `open_test.py`）/ added `perf_ui.py` (headless Chrome measures fps with 2500 cards), `library_ui.py` (the library screens, with a fake Spotify), `library_test.py`, `library_unit.py`, `spotify_unit.py`, `audio_unit.py` and `link_test.py` (replaces `open_test.py`)

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
