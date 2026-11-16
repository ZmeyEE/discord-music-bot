# Security / 資安

## 回報漏洞 / Reporting a vulnerability

請**不要**直接開公開的 issue 講漏洞細節，請用 GitHub 的 "Report a vulnerability"（Security 分頁 → Advisories）私下回報
Please do **not** open a public issue with the details, use GitHub's "Report a vulnerability" (Security tab → Advisories) to report it privately

## 設計上的重點 / Design notes

- 看板的入口只有 `/help` 給的專屬連結（2.0 起沒有"知道網址就能控制"的 `open` 模式）；連結等同你的身分，不要轉貼給別人 / the only way into the dashboard is the personal link from `/help` (since 2.0 there is no `open` mode where knowing the URL is enough); the link is your identity, don't share it
- `verify` 模式：只有 Discord 伺服器成員用 /help 的專屬連結進得來，瀏覽器存一把隨機憑證，主機只存雜湊 / `verify` mode: only server members get in through their personal /help link, the browser keeps a random token and the host stores only its hash
- 更換 Bilibili 帳號永遠只限擁有者或本機 / switching the Bilibili account is always limited to the owner or the local machine
- 中繼站：HMAC 挑戰握手（金鑰不上線）、每個 IP 的連線與頻率上限、握手失敗暫時封鎖、嚴格的安全標頭 / relay: HMAC challenge handshake (the key never travels), per-IP caps, temporary lock-out after failed handshakes, strict security headers
- 機密檔（`.env`、`cookies.txt`、`settings.json`、`members.json`）都在 `.gitignore`，cookie 等同登入憑證，請勿分享 / secret files are in `.gitignore`, cookies are equivalent to a login, never share them

## 已知問題 / Known issues

- **PyNaCl**：1.1.0 起要求 `>=1.6.2`（1.5.0 有 CVE-2025-69277 等 2 個已知問題）。`discord.py[voice]` 把它鎖在 `<1.6`，所以 `requirements.txt` 直接列出 PyNaCl 和 davey，不用 `[voice]`，全部測試在 1.6.2 上通過；如果你的環境是舊的，重新跑 `pip install -r requirements.txt` 就會升級
  **PyNaCl**: since 1.1.0 it must be `>=1.6.2` (1.5.0 has CVE-2025-69277 and one more known issue). `discord.py[voice]` pins it to `<1.6`, so `requirements.txt` lists PyNaCl and davey directly instead of `[voice]`; all tests pass on 1.6.2. If your environment is old, run `pip install -r requirements.txt` again to upgrade
- **davey 要鎖 `<0.2`**：discord.py 2.7.1（目前最新）還不支援 davey 0.2，升上去會變成"能進頻道但沒有聲音"，啟動時有檢查會擋下來 / **davey must stay `<0.2`**: discord.py 2.7.1 (the latest) doesn't support davey 0.2 yet, upgrading gives "joins but silent", and a start-up check stops it
- 中繼站預設綁定 `0.0.0.0`（本來就是給公網用的），只想在本機測試的話，在 `.env` 設 `RELAY_HOST=127.0.0.1` / the relay binds `0.0.0.0` by default (it is meant for the public internet), set `RELAY_HOST=127.0.0.1` in `.env` for local testing only

## 發版前檢查 / Pre-release checks

1. 機密掃描：確認沒有 Token、金鑰、ID、IP、個人路徑 / secret scan: no tokens, keys, IDs, IPs or personal paths
2. `pip-audit -r requirements.txt` 檢查相依套件的已知漏洞 / check dependencies for known vulnerabilities
3. `bandit -r musicbot launcher bot.py` 靜態檢查 / static check
4. 跑完 `tests/` 全部測試 / run all the tests in `tests/`

## 不在範圍內 / Out of scope

- 使用者自己公開了 Token 或專屬連結 / users who leak their own token or personal link
- 平台（Discord、Bilibili、YouTube）本身的問題與服務條款 / problems or terms of the platforms themselves

## 2.0 新增的資料 / Data added in 2.0

- `library.json`：每個人的歌單與資料夾（只有連結和顯示用的資料）。只在執行機器人的這台電腦上，不會傳到中繼站，已列入 `.gitignore` / each person's playlists and folders (links and display data only). It stays on the machine that runs the bot, never goes to the relay, and is in `.gitignore`
- `spotify_tokens.json`：連結 Spotify 的人的 refresh token，等於對方的 Spotify 讀取權限（只能讀歌單）。只在這台電腦，不進 git，網頁拿不到它，登出就刪掉；請當成密碼保管 / the refresh tokens of people who linked Spotify, which is their read access to Spotify (playlists only). It stays on this machine, is not in git, the page never receives it, and logging out deletes it; keep it like a password
- 授權碼 + PKCE 沒有 Client Secret 要保管；授權進行中的暫存只在記憶體、10 分鐘過期、只有發起的人貼得回來 / authorisation code + PKCE leaves no client secret to keep; the pending state is in memory only, expires after 10 minutes and only the person who started it can finish it
- 歌單操作一律用 `/help` 連結裡的 Discord 身分，每個人只看得到也只能動自己的 / every library action uses the Discord identity from the `/help` link; everyone sees and edits only their own
