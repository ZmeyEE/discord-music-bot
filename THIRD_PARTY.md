# 第三方開源元件 / Third-party components

本專案本身以 [Unlicense](LICENSE) 釋出（公有領域），但它使用了下面這些別人的開源作品，各自保有原本的授權
This project itself is released under the [Unlicense](LICENSE) (public domain), but it uses the open-source work of others listed below, and each keeps its own license

## 1. Python 套件 / Python packages

用 `pip install -r requirements.txt` 安裝，專案沒有把它們的原始碼放進來，只是使用
Installed with `pip install -r requirements.txt`; their source is not copied into this repo, the project only uses them

| 套件 / Package | 用途 / What we use it for | 授權 / License | 備註 / Notes |
| --- | --- | --- | --- |
| [discord.py](https://github.com/Rapptz/discord.py) (`[voice]`) | 連 Discord、斜線指令、語音 / Discord API, slash commands, voice | MIT | 會順帶安裝 PyNaCl（Apache-2.0）/ also pulls in PyNaCl (Apache-2.0) |
| [davey](https://pypi.org/project/davey/) | Discord 語音端對端加密 DAVE / Discord voice end-to-end encryption (DAVE) | MIT | **版本要鎖在 `<0.2`**，原因見 `requirements.txt` / **must stay `<0.2`**, see `requirements.txt` for why |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | 解析 Bilibili／YouTube 網址、取得音訊串流 / resolve Bilibili / YouTube URLs into audio streams | Unlicense | 網站常改版，壞掉先跑 `update-ytdlp.bat` / sites change often, run `update-ytdlp.bat` first when it breaks |
| [aiohttp](https://github.com/aio-libs/aiohttp) | 網頁看板、WebSocket、中繼站、對外 HTTP 請求 / dashboard, WebSocket, relay, outgoing HTTP | Apache-2.0 | 中繼站只靠它 / the relay depends on this alone (`requirements-relay.txt`) |
| [segno](https://github.com/heuer/segno) | 產生 Bilibili 登入的 QR 碼 / generate the Bilibili login QR code | BSD-3-Clause | 純 Python、無相依 / pure Python, no dependencies |

## 2. 隨附的檔案 / Files bundled in this repo

這是唯一把別人的原始碼放進 repo 的地方，授權標頭請保留，不要刪
The only place where someone else's source is copied into the repo; please keep the license header

| 檔案 / File | 來源 / Source | 授權 / License |
| --- | --- | --- |
| `web/vendor/Sortable.min.js` | [SortableJS](https://github.com/SortableJS/Sortable) 1.15.6 | MIT |

## 3. 外部程式（要自己安裝）/ External programs (install yourself)

| 程式 / Program | 用途 / What we use it for | 授權 / License | 備註 / Notes |
| --- | --- | --- | --- |
| [FFmpeg](https://ffmpeg.org/) | 把音訊轉成 Opus 再送進 Discord / transcode audio to Opus for Discord | LGPL-2.1+ 或 GPL-2+（看編譯版本）/ LGPL-2.1+ or GPL-2+ (depends on the build) | 沒有內附，授權責任在安裝的人 / not bundled, the license duty belongs to whoever installs it |
| [PyInstaller](https://pyinstaller.org/)（選用 / optional） | 把 `launcher/launcher.py` 打包成 `.exe` / package the launcher into an `.exe` | GPL-2.0 + 打包例外 / GPL-2.0 with a bootloader exception | 只有要自己打包時才需要 / only needed if you build the exe yourself |

## 4. 看板載入的資源 / Resources the dashboard loads

| 資源 / Resource | 授權 / License | 備註 / Notes |
| --- | --- | --- |
| [粉圓 Huninn](https://fonts.google.com/specimen/Huninn) 字體 / font | SIL OFL 1.1 | 由 Google Fonts 載入，離線時退回系統字體 / loaded from Google Fonts, falls back to system fonts offline |
| [Nunito](https://fonts.google.com/specimen/Nunito) 字體 / font | SIL OFL 1.1 | 同上 / same as above |

載入字體時，瀏覽器會連到 Google Fonts；不想這樣的話，把 `web/index.html` 裡 Google Fonts 的三行 `<link>`（字體註解下方）刪掉即可，畫面會改用系統字體
Loading the fonts makes the browser contact Google Fonts; to avoid that, remove the three Google Fonts `<link>` lines in `web/index.html` (just under the font comment) and the page will use system fonts

## 5. 服務與平台 / Services and platforms

這些不是函式庫，但使用時要遵守它們的條款
These are not libraries, but their terms apply when you use them

- **Discord**：[Developer Terms](https://discord.com/developers/docs/policies-and-agreements/developer-terms-of-service) 與 Developer Policy / Developer Terms and Developer Policy
- **Bilibili**：官方登入 API 與服務條款，只儲存登入後的 cookie，不接觸密碼 / official login API and its terms; only the resulting cookies are stored, never the password
- **YouTube 與其他 yt-dlp 支援的網站 / YouTube and other yt-dlp sites**：各站的服務條款與當地著作權規定 / each site's terms and local copyright law
- **Spotify**：只讀公開嵌入頁的歌名和歌手，不下載也不播放 Spotify 的音訊，沒有用 Spotify API 也不需要金鑰 / only reads title and artists from the public embed page, never downloads or plays Spotify audio, no Spotify API and no key
- **Cloudflare Quick Tunnel、Tailscale 等（選用）/ optional**：只在你選擇用它們分享看板時才會用到 / only when you choose them to share the dashboard

## 給開發者的提醒 / Notes for contributors

1. **新增相依套件時**：把它寫進 `requirements.txt`（中繼站用的寫進 `requirements-relay.txt`），並在這份文件補一列，標明用途與授權
   **When adding a dependency**: put it in `requirements.txt` (or `requirements-relay.txt` for the relay) and add a row here with its purpose and license
2. **不要把別人的程式碼直接貼進來**，除非授權允許，而且要在這份文件的第 2 節登記，並保留原本的授權標頭
   **Do not paste other people's code in** unless the license allows it; register it in section 2 and keep the original license header
3. **打包成單一 `.exe` 散布時**：FFmpeg 與各套件的散布條件要重新檢查，目前的專案形式（只使用、不內附）不需要這樣做
   **If you ship one bundled `.exe`**: re-check the distribution terms of FFmpeg and every package; the current form (use only, nothing bundled) does not need that
4. 這份清單是整理給大家參考的，不是法律意見；實際授權以各專案官方的授權文字為準
   This list is a convenience for contributors, not legal advice; the official license text of each project is what counts
