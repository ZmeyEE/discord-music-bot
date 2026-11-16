# 開發者指南（繁體中文）

本地執行，完全 free 高音質 Discord 音樂 bot，Bilibili 優先，另附卡片式網頁看板
這份給想改它的人：新增語言、改配色、優化音源到 Discord 的路徑、把看板 UI 用在別的地方
(English version: [DEVELOPING.en.md](DEVELOPING.en.md))

版本：**1.2.0** · 授權：[Unlicense](../LICENSE)（公有領域，想怎麼改都可以）· 第三方清單：[THIRD_PARTY.md](../THIRD_PARTY.md)

## 1. 專案地圖

```
bot.py                 進入點，只呼叫 musicbot.app.main()
musicbot/
  params.py            所有可以調的數字都在這一個檔案（見下面）
  app.py               啟動：讀設定、建立 Hub、看板、中繼站連線、卡頓偵測、登入每個機器人
  tuning.py            啟動時的檢查與調整（davey 版本、重連上限、Windows 優先權）
  logging_setup.py     記錄檔，權杖會遮蔽
  config.py paths.py   .env、settings.json、ffmpeg 位置、檔案位置
  auth.py members.py   簽名連結、記住的裝置（只存雜湊）
  bilibili.py          Bilibili 掃碼登入、帳號資訊
  webutil.py netinfo.py addclone.py   安全標頭、區網位址、加分身小工具
  sources/             網址／關鍵字／Spotify → 曲目 → 音訊串流（yt-dlp）
    tracks.py recognize.py resolve.py spotify.py match.py stream.py
  player/              一個 Discord 機器人帳號 = 一個 PlayerBot
    state.py voice.py playback.py recover.py enqueue.py controls.py snapshot.py bot.py
  hub/                 總指揮：誰能控制、哪個機器人播、狀態快照、操作
    models.py identity.py routing.py streams.py snapshot.py actions.py bili.py core.py
  health/              卡頓偵測，電腦跟不上時由最後加入的頻道開始停
    probe.py ledger.py monitor.py
  commands/            斜線指令（/play /help /quality …）
    helpers.py info.py voice.py controls.py
  dashboard/           本機網頁伺服器（靜態檔 + WebSocket）與 DashboardCore
    session.py queuewindow.py core.py server.py   （queuewindow：每個瀏覽器只拿一頁待播清單，沒變就不重送）
  relay/               選用的中繼站（VPS／樹莓派），只轉送訊息
    util.py limits.py worker.py browser.py server.py cli.py
  relay_client.py      家裡的 bot 主動連出去連中繼站
web/                   看板前端，原生 HTML / CSS / JS，不用建置
  js/                  ES 模組，從 main.js 看起，由下往上讀（先 util / store / dom）
  i18n.js              看板語言
tests/                 回歸測試（Discord 語音層用假的）
launcher/              桌面啟動／關閉小視窗（tkinter，選用）
  botpanel/            paths.py procs.py theme.py widgets.py window.py actions.py logview.py（配色在 theme.py，和看板一致）
  build.py             打包成 dist/MusicBotLauncher-<版本>.exe（python launcher/build.py），版本在 botpanel/__init__.py
deploy/                中繼站的 systemd 服務
```

重點：**一個 Discord 機器人帳號在同一個伺服器只能待一個語音頻道**，所以要多頻道同時播放就加分身帳號
（`add-clone.bat`），全部由 `Hub` 統一協調

程式怎麼切：一個資料夾 = 一個功能，一個檔案只做一件事、盡量短（最多約 200 行）
太大的類別拆成 mixin（`VoiceMixin`、`PlaybackMixin`…），在 `bot.py`／`core.py` 組起來，方法還是用 `self.`，其他都沒變
由下往上讀：先看小工具和資料結構，再看各功能，最後看組起來的那個檔案

### 調整參數（`musicbot/params.py`）

想調的數字都在這一個檔案：音質選項、清單與合集上限、補縮圖、Spotify 對應的容許誤差、閒置離開、重連與救援時間、
卡頓偵測的每個門檻、看板與中繼站的限制、憑證有效期，每個都有註解，存檔後重開機器人就生效

標 `ENV` 的也可以在 `.env` 設定（`.env` 優先），其他檔案是用 `params.名稱` 在用到的時候才讀，所以不要把數字另外抄到別的檔案

## 2. 開發環境

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt      # Linux / macOS：.venv/bin/python
copy .env.example .env                                           # 再把 DISCORD_TOKEN 填進去
.venv\Scripts\python.exe bot.py
```

還要有 ffmpeg（在 PATH，或在 `.env` 設 `FFMPEG_PATH`）
`.env`、`cookies.txt`、`settings.json`、`members.json` 絕對不要 commit（`.gitignore` 已擋）

## 3. 跑測試

```bash
.venv\Scripts\python.exe tests\run_all.py              # 全部
.venv\Scripts\python.exe tests\run_all.py verify       # 只跑名稱含 verify 的
.venv\Scripts\python.exe tests\run_relay.py            # 中繼站
```

測試會啟動真的 `Hub`、`Dashboard`、`PlayerBot`，只有 Discord 語音層是假的（`tests/harness_hub.py`）
需要網路（會解析一支 Bilibili 影片）和 ffmpeg，而且不會動到你正式的 `settings.json`、`members.json`
詳細說明在 [tests/README.md](../tests/README.md)

送 PR 前請先跑過，加新功能也請順便加測試

## 4. 改配色（背板、卡片、字體）

視覺全部在 `web/style.css`，顏色是最上面的變數

```css
:root {
  --cream: #F7E0D3;  --rose: #E3C2C6;  --lavender: #AFAFC8;  --steel: #5F7EAE;   /* 調色盤 */
  --ink: #33405E;    --accent: #54739F;                                          /* 文字、按鈕 */
  --card: #FFF9F4;   --radius: 18px;                                             /* 卡片 */
  --font: "Huninn", ...;                                                         /* 字體 */
}
```

- **調色盤／文字／按鈕／卡片顏色**：改 `:root` 的變數，整個頁面會跟著變
- **背板**：天空是 `body::before` 的漸層（固定圖層，只畫一次，捲動和拖曳才不會卡），改那裡的 `linear-gradient(...)` 和兩個 `radial-gradient(...)`
- **字體**：`--font`、`--font-num`，Google Fonts 的 `<link>` 在 `web/index.html` 最上面（不想讓瀏覽器連 Google 就刪掉，會退回系統字體）
- **圖示**：手繪 SVG 圖示庫在 `web/index.html` 最上面，用 `<svg class="i"><use href="#i-名稱"/></svg>`（或 `web/js/util.js` 裡的 `icon("名稱")`）
- 文字對比要夠（預設文字 > 7:1，按鈕白字 > 4.5:1）
- 不用建置，存檔後重新整理瀏覽器就看得到

## 5. 新增語言

1.1.0 起網頁看板有多語言了（繁中、簡中、English、日本語），Discord 訊息和斜線指令還沒有

**網頁看板加語言**（`web/i18n.js`）：

1. 在 `LANGS` 加一行，例如 `["ko", "한국어"]`，`HTML_LANG` 加對應的 `<html lang>`
2. 照 `"zh-TW"` 那一組，在 `D` 裡新增同名的一組，把每個 key 翻過去
3. 缺的 key 會自動用繁體中文，所以可以先翻一部分
4. 重新整理就看得到，右上角選單會多一個選項

用法：HTML 標 `data-i18n="key"`（文字）、`data-i18n-html`（有 `<b>` `<code>` 的）、`data-i18n-title`／`-aria`／`-ph`／`-alt`；JS 用 `T("key", { name: "x" })`，`{name}` 會被換掉

換語言會存在瀏覽器（`localStorage` 的 `mb_lang`）然後重新整理，所以不用處理畫面上的舊文字

**還沒做的**（找字串：`rg "[一-鿿]" musicbot`）：

| 位置 | 內容 |
| --- | --- |
| `musicbot/commands/` | 斜線指令名稱、說明、回覆 |
| `musicbot/hub/` `player/` `dashboard/` `health/` `relay/` | 公告、錯誤，會顯示在看板的提示也在這裡 |

1. **伺服器回覆**：字串集中到一個 `messages.py`，用 id 當 key，語言由 `.env` 設定（例如 `BOT_LANG=en`）
2. **斜線指令**：discord.py 支援指令在地化（`app_commands.locale_str` + `Translator`）
3. 預設維持繁體中文，並加一個測試確認每個語言的 key 都齊全

## 6. 優化音源 → Discord 的路徑

```
網址 --> sources.resolve_tracks --> 待播 --> player.ensure_playing --> sources.extract_stream (yt-dlp)
     --> player._play_stream (ffmpeg -> Opus) --> Discord 語音
```

- **yt-dlp 挑哪條音軌**：`sources.extract_stream` 的 `"format"` 字串，現在是 `bestaudio[acodec=flac]/bestaudio[acodec!*=ec-3]/bestaudio/best`（帳號拿得到就用無損 FLAC，其次是最佳一般音軌，並略過杜比 E-AC-3，因為多聲道降混成立體聲反而變差）
- **Bilibili 登入／大會員**：`bilibili.py` 寫出 `cookies.txt`，`sources/tracks.py` 交給 yt-dlp，大會員帳號才能拿到無損 Hi-Res（這條路徑作者沒有大會員帳號，**尚未實測**）
- **ffmpeg 怎麼被呼叫**：`player.PlayerBot._play_stream`
  - `before_options`：自動重連、請求標頭、跳轉用的 `-ss`（放在 `-i` 前面 = 快速跳轉）
  - `options="-vn"`：去掉影像，想加輸出參數就放這裡，例如音量平衡 `-af loudnorm`
  - 沒有指定 codec，所以 discord.py 會用 libopus 以我們給的位元率重新編碼（Discord 只收 Opus，一定會重編一次，目標是"最好的來源 → 最高的 Opus 位元率"）
- **位元率**：`config.target_bitrate()` = 伺服器音質設定與語音頻道本身位元率較高者，限制在 Opus 的 8 - 510 kbps，選項在 `config.QUALITY_CHOICES`
- **卡頓偵測**：`health/probe.py` 包住音訊來源（`probe_source`），只量測送包時間，不會改動聲音，改路徑時請維持這點
- 改完請實際聽過，再跑 `tests\run_all.py quality` 和 `seek`

注意：discord.py 2.7.x 搭配的 `davey` 要鎖 `<0.2`（否則 bot 進得了語音但完全沒聲音），網站常改版，搜尋或播放壞掉先跑 `update-ytdlp.bat`

## 7. 把看板 UI 用在別的地方

前端是原生 HTML / CSS / JS，只內附 [SortableJS](https://github.com/SortableJS/Sortable)
它和後端只透過**一條 WebSocket**（`/ws/<伺服器 id>`）溝通，傳小小的 JSON，所以任何會講同樣訊息的後端都能驅動它

伺服器 → 瀏覽器：

| `type` | 意思 |
| --- | --- |
| `state` | 完整狀態：正在播放、待播、頻道、權限（`me`）、音質、Bilibili 帳號（由 `Hub.snapshot` 產生）|
| `toast` | 要顯示的短訊息 |
| `error` | 出問題了（`code`：`guild`、`auth`、`offline`…）|
| `verified` / `revoked` | 發出／收回裝置憑證（驗證模式）|

瀏覽器 → 伺服器（`Hub.handle_action` 與 `DashboardCore`）：

`add` `move` `remove` `remove_current` `play_now` `skip` `seek` `toggle_pause` `stop` `shuffle` `clear` `loop` `quality` `select` `bili_login_start` `bili_login_cancel` `bili_logout`

點子：

- **換音樂來源／換聊天平台**：`web/` 原封不動，寫一個後端提供 `web/` 和 `/ws/<id>`，組出同樣的 `state` 物件
- **只要卡片的外觀**：複製 `web/style.css` 的 `.card` 與子元素、`web/js/cards.js` 的 `makeCard()` 和調色盤變數，它們不依賴音樂程式
- **拖曳排序／拖到垃圾桶**：看 `web/js/dragdrop.js` 的 Sortable 設定和 CSS 的 `.trash`
- 卡片式 UI 也獨立成一個庫了：[dusk-cards](https://github.com/ZmeyEE/dusk-cards)（原生 JS + CSS，公有領域）

## 8. 給貢獻者的資安規則

- 不要把 Token、cookie、ID、IP、個人路徑放進程式、註解、測試或截圖
- 權限檢查一律在**伺服器端**（`Hub.can_control`），瀏覽器永遠不可信
- 中繼站新增任何端點，都要有限流，並在 `tests/harden_test.py` 加測試
- 發版前跑一次機密掃描和相依套件稽核（`pip-audit`），見 [SECURITY.md](../SECURITY.md)

## 9. 發版

1. 改 `musicbot/__init__.py` 的 `__version__`（[SemVer](https://semver.org/lang/zh-TW/)：修 bug = patch，加功能 = minor，不相容 = major）
2. 把變更寫進 [CHANGELOG.md](../CHANGELOG.md)
3. 跑完全部測試，打 `vX.Y.Z` tag，建立 GitHub release

## 10. 程式風格

- 註解中英雙語，簡短、親切，說明**為什麼**，不只是做什麼
- 中文標點用逗號 ， 和半形引號，不用日式直角引號，也不用句號（跟整個專案一致）
- 函式小一點、一個函式一件事，每個函式都要有 docstring
