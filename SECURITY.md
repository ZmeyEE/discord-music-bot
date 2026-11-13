# Security / 資安

## 回報漏洞 / Reporting a vulnerability

請**不要**直接開公開的 issue 講漏洞細節，請用 GitHub 的 "Report a vulnerability"（Security 分頁 → Advisories）私下回報
Please do **not** open a public issue with the details, use GitHub's "Report a vulnerability" (Security tab → Advisories) to report it privately

## 設計上的重點 / Design notes

- 看板預設是 `open` 模式：能連到網址的人就能控制播放，所以只在你信任的網路使用，要放到公開網路請用 `verify` / the dashboard defaults to `open`: anyone who can reach the URL controls playback, so use it on networks you trust and switch to `verify` when exposing it publicly
- `verify` 模式：只有 Discord 伺服器成員用 /help 的專屬連結進得來，瀏覽器存一把隨機憑證，主機只存雜湊 / `verify` mode: only server members get in through their personal /help link, the browser keeps a random token and the host stores only its hash
- 更換 Bilibili 帳號永遠只限擁有者或本機 / switching the Bilibili account is always limited to the owner or the local machine
- 中繼站：HMAC 挑戰握手（金鑰不上線）、每個 IP 的連線與頻率上限、握手失敗暫時封鎖、嚴格的安全標頭 / relay: HMAC challenge handshake (the key never travels), per-IP caps, temporary lock-out after failed handshakes, strict security headers
- 機密檔（`.env`、`cookies.txt`、`settings.json`、`members.json`）都在 `.gitignore`，cookie 等同登入憑證，請勿分享 / secret files are in `.gitignore`, cookies are equivalent to a login, never share them

## 已知問題 / Known issues

- **PyNaCl 1.5.0（CVE-2025-69277，libsodium 的 `crypto_core_ed25519_is_valid_point`）**：`pip-audit` 會回報，修正版是 1.6.2，但 discord.py 目前把它鎖在 `<1.6`，所以暫時不能升級；這個專案不會呼叫該函式（那是特殊用途的自訂密碼學），Discord 語音只用一般的加解密，實際不受影響，discord.py 放寬版本限制後會跟進升級
  **PyNaCl 1.5.0 (CVE-2025-69277, libsodium `crypto_core_ed25519_is_valid_point`)**: reported by `pip-audit`, fixed in 1.6.2, but discord.py currently pins it to `<1.6` so it can't be upgraded yet; this project never calls that function (it is for special custom cryptography), Discord voice only uses ordinary encryption, so it is not affected in practice; we will upgrade once discord.py relaxes the pin
- 中繼站預設綁定 `0.0.0.0`（本來就是給公網用的），只想在本機測試的話，在 `.env` 設 `RELAY_HOST=127.0.0.1` / the relay binds `0.0.0.0` by default (it is meant for the public internet), set `RELAY_HOST=127.0.0.1` in `.env` for local testing only

## 發版前檢查 / Pre-release checks

1. 機密掃描：確認沒有 Token、金鑰、ID、IP、個人路徑 / secret scan: no tokens, keys, IDs, IPs or personal paths
2. `pip-audit -r requirements.txt` 檢查相依套件的已知漏洞 / check dependencies for known vulnerabilities
3. `bandit -r musicbot launcher bot.py` 靜態檢查 / static check
4. 跑完 `tests/` 全部測試 / run all the tests in `tests/`

## 不在範圍內 / Out of scope

- 使用者自己公開了 Token 或把看板用 `open` 模式放到公開網路 / users who leak their own token or expose an `open` dashboard to the public internet
- 平台（Discord、Bilibili、YouTube）本身的問題與服務條款 / problems or terms of the platforms themselves
