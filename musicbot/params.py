"""所有可以調的參數，集中在這一個檔案
改這裡就好，其他檔案不用動，存檔後重開機器人就生效
有 ENV 標記的也可以在 .env 設定（.env 優先）

Every tunable parameter lives in this one file.
Change it here and nothing else needs to be touched: save and restart the bot.
Values marked ENV can also be set in .env (.env wins).

其他檔案一律用 ``params.名稱`` 讀取，不要自己再寫一份數字
Other modules always read ``params.NAME``; never copy a number into another file.
"""
from __future__ import annotations

import os


def _env_int(name: str, default: int) -> int:
    """讀整數環境變數，沒設或格式錯就用預設 / Read an integer env var, fall back to the default if missing or malformed."""
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# =====================================================================
# 1. 音質 / Audio quality
# =====================================================================
QUALITY_CHOICES = (128, 192, 256, 320, 510)   # 看板與 /quality 的音質選項（Opus 位元率 kbps；510 是 Opus 規格上限）/ quality choices for the dashboard and /quality (Opus kbps; 510 is the Opus spec maximum)
DEFAULT_BITRATE_KBPS = 192                    # 沒有任何設定時的預設音質 / default when nothing is configured

# =====================================================================
# 2. 清單、搜尋與縮圖 / Queue, search and thumbnails
# =====================================================================
MAX_PLAYLIST = 5000        # 合集／播放清單一次最多加入幾首 / max tracks taken from one playlist
MAX_QUEUE = _env_int("MAX_QUEUE", 5000)   # ENV  一個伺服器的待播清單最多幾首 / max songs in one server's queue
QUEUE_VIEW = 1000        # 看板一次最多畫幾張待播卡片，5000 首全送一次要 1.7MB，中繼站單則訊息上限 4MB / cards the dashboard draws at once: all 5000 songs are 1.7 MB per update and the relay caps a message at 4 MB
SEARCH_CACHE_TTL = 600  # 秒；相同關鍵字短時間內不要重複打站方 API / seconds; don't hit the site's API again for the same keywords
ENRICH_FIRST = 50        # 加歌時先補幾首的縮圖與標題 / how many songs get their thumbnail and title filled right when added
ENRICH_AHEAD = 10        # 開始播一首時，往後再補幾首 / when a song starts, how many following songs are filled
ENRICH_PARALLEL = 3      # 同時補幾首（太多會被站方限流）/ how many are filled at the same time (more gets rate-limited)

# =====================================================================
# 3. Spotify 對應歌曲 / Spotify song matching
# =====================================================================
MATCH_CANDIDATES = 5            # 搜尋時看前幾筆 / how many search hits are considered
MATCH_TOLERANCE_SECONDS = 6.0   # 長度差在這幾秒內算同一首 / a duration gap within this many seconds is the same song
MATCH_TOLERANCE_RATIO = 0.05    # 或差在原曲長度的這個比例內（兩者取大）/ or within this share of the song length (the larger of the two wins)

# =====================================================================
# 4. 語音與閒置離開 / Voice and idle auto-leave
# =====================================================================
# 閒置自動離開（秒），分身離開語音頻道後才能被其他頻道接手；設成 0 代表不自動離開
# Idle auto-leave (seconds). A clone can only be taken over by another channel after it leaves; 0 = never leave.
MAX_QUEUE = _env_int("MAX_QUEUE", 5000)                      # 一個伺服器的待播清單最多幾首 / max songs in one server's queue
QUEUE_VIEW = 1000   # 看板一次最多畫幾張待播卡片，5000 首全送一次要 1.7MB，中繼站單則訊息上限 4MB / cards the dashboard draws at once: all 5000 songs are 1.7 MB per update and the relay caps a message at 4 MB
EMPTY_LEAVE_SECONDS = _env_int("EMPTY_LEAVE_SECONDS", 120)   # 頻道內只剩機器人 / only bots left in the channel
IDLE_LEAVE_SECONDS = _env_int("IDLE_LEAVE_SECONDS", 300)     # 沒有在播也沒有待播 / nothing playing and nothing queued

# Discord 閘道斷線後，語音被踢掉（4014）的歌，這段秒數內會自動回頻道接著播，超過就當作是人踢的
# If Discord's gateway dropped and then kicked us from voice (4014) within this many seconds, rejoin and resume; otherwise a human kicked us.
RECOVER_WINDOW = 900.0
RECOVER_SECONDS = 600.0   # 回頻道最多試多久（頻道沒人就等人回來）/ how long to keep trying to rejoin (waits for people if the channel is empty)
IDLE_CHECK_SECONDS = 20          # 多久檢查一次閒置 / how often the idle check runs
RESERVE_SECONDS = 60.0           # 選到分身後預約幾秒，解析網址期間不會被別人搶走 / how long a picked clone stays reserved while the URL resolves
VOICE_CHECK_DELAYS = (4, 16)     # 開始播放後第幾秒檢查語音連線／加密狀態（寫進記錄）/ seconds after playback starts when the voice link and encryption are checked (logged)

# =====================================================================
# 5. 斷線重連 / Reconnecting
# =====================================================================
RECONNECT_MAX_EXP = 4        # 重連等待 = 隨機 0 ~ 2^n 秒，n 最大值；4 = 最多 16 秒（discord.py 預設 10，最久約 17 分鐘）/ reconnect wait = random 0..2^n s, max n; 4 = up to 16 s (discord.py's own is 10, up to ~17 min)
RECOVER_FIRST_DELAY = 3.0    # 救援回語音頻道：第一次等幾秒 / rejoin after a kick: first wait in seconds
RECOVER_MAX_DELAY = 30.0     # 每次加倍，最多等幾秒 / doubles each time, up to this many seconds

# =====================================================================
# 6. 卡頓偵測 / Stutter detection
# =====================================================================
# ---- 事件偵測（探針）/ event detection (the probe) ----
LATE_GAP = 0.060          # 相鄰兩次讀取相隔超過這個秒數 = 一次卡頓事件 / gap between two reads above this = one stutter event
STARVE_READ = 0.040       # 單次讀取 ffmpeg 超過這個秒數 = 來源／編碼跟不上 / a single ffmpeg read slower than this = source/encoder can't keep up
RESUME_GAP = 1.5          # 間隔超過這個秒數 = 暫停／跳轉後恢復，不是卡頓 / a gap longer than this = resumed after pause/seek, not a stutter
WARMUP = 3.0              # 開播前幾秒是 ffmpeg 暖機，不計 / the first seconds of a song are ffmpeg warm-up and are ignored

# ---- 判斷（濾波＋歸因＋緩衝）/ judgement (filtering + attribution + buffering) ----
CHECK_INTERVAL = 5.0
SETTLE = 8.0              # 串流數剛改變後，前幾秒（新串流暖機、連線建立）不計入觀察 / right after the stream count changes, ignore a few seconds (warm-up, connection set-up)
RECENT = 60.0             # "現在的狀況"看最近這麼多秒 / how many recent seconds describe "the current situation"
OBS_MIN = 30.0            # 現在這個狀態至少要觀察這麼久才下判斷 / the current state must be observed this long before judging
BASE_MIN = 40.0           # "少一條"的狀態至少要觀察過這麼久，才能當作乾淨的對照 / the "one fewer" state must have been observed this long to serve as a clean baseline
BAD_EVENTS = 4            # 最近 RECENT 秒內至少幾次事件 / at least this many events within RECENT seconds
BAD_TICKS = 3             # ……而且分散在至少幾個不同的 5 秒區間（排除一次爆發）/ ...spread over at least this many different 5 s slots (rules out a single burst)
BAD_SPAN = 20.0           # ……而且第一次到最後一次事件至少相隔這麼多秒（卡頓要"持續"一段時間，不是短短一陣）/ ...first-to-last event at least this many seconds apart (it must be sustained, not a brief blip)
BAD_RATE = 6.0            # ……而且每分鐘至少這麼多次 / ...and at least this many per minute
CLEAN_RATE = 1.5          # 對照狀態每分鐘最多這麼多次才算乾淨 / the baseline state may have at most this many per minute to count as clean
ATTRIB_WINDOW = 300.0     # 卡頓必須出現在最後一個頻道加入後這麼多秒內，才怪它 / stutter must appear within this many seconds of the last join to blame it
REMOVE_COOLDOWN = 90.0    # 停掉一個之後，至少隔這麼久才會再判斷 / after a removal, wait at least this long before judging again
HOLD_SECONDS = 600.0      # 停掉之後，這麼久之內不再派新的頻道進來 / after a removal, assign no new channels for this long
HISTORY = 900.0           # 保留多久的歷史當對照 / how much history to keep as a reference
GRACE = 30.0              # 一個頻道暫時沒在出聲（換歌載入、短暫暫停）這麼久以內，仍算"占用中"，不當成離開再加入 / a channel silent this long (song change, short pause) still counts as "occupied", not as leave + re-join

# 只用來在公告裡說明原因的門檻 / thresholds used only to explain the cause in the announcement
CPU_HIGH = 88.0           # 系統 CPU 使用率（%）/ system CPU usage (%)
LOOP_LAG_HIGH = 0.12      # 事件迴圈延遲（秒）/ event-loop lag (s)
LATENCY_HIGH = 0.30       # 語音連線延遲（秒）/ voice connection latency (s)

# =====================================================================
# 7. 看板與身分 / Dashboard and identity
# =====================================================================
BROADCAST_MERGE_SECONDS = 0.05   # 狀態變更後等這麼久再廣播，期間的變更合併成一次 / wait this long before broadcasting, changes in between are merged
DEFAULT_TTL = 12 * 3600   # 12 小時；過期後再輸入一次 /help 即可 / 12 hours; type /help again after it expires
DEVICE_TTL = 90 * 24 * 3600     # 裝置憑證多久沒用就失效（每次使用會順延）/ a device token expires after this long unused (each use extends it)
QR_LIFETIME = 180   # 秒；QR 碼的有效時間（Bilibili 約 3 分鐘）/ seconds a QR code stays valid (about 3 minutes)
SEEN_RESOLUTION = 3600          # "最後使用"最多每小時寫一次檔 / "last seen" is written to disk at most once per hour
INVITE_PERMISSIONS = 1024 + 2048 + 16384 + 1048576 + 2097152

# =====================================================================
# 8. 中繼站 / Relay
# =====================================================================
HELLO_INTERVAL = 30.0   # 沒有變化時，每隔幾秒送一次心跳 / seconds between heartbeat "hello" messages when nothing changed
MAX_BROWSERS = 300           # 同時連線的瀏覽器上限 / max simultaneous browsers
MAX_PER_IP = 12              # 同一個來源 IP 同時最多幾個瀏覽器連線（避免一個人把名額占滿）/ max simultaneous browsers per source IP (stops one person hogging all slots)
NEW_PER_MINUTE = 40          # 同一個來源 IP 每分鐘最多幾次新連線（擋掃描與灌連線）/ max new connections per IP per minute (blocks scans and floods)
MAX_MSG_BYTES = 64 * 1024    # 瀏覽器單則訊息大小上限 / max size of one browser message
RATE_PER_SEC = 25            # 每個瀏覽器每秒最多轉送幾則（超過的丟掉，保護家裡的機器人）/ messages forwarded per browser per second (extra ones are dropped to protect the home bot)
BURST = 60                   # 瞬間可累積的額度（token bucket 容量）/ burst allowance (token-bucket capacity)
AUTH_TIMEOUT = 10.0          # 握手最多等幾秒 / seconds to wait for the handshake answer
MAX_HANDSHAKES_PER_IP = 3    # 同一個來源 IP 同時最多幾個"還沒完成握手"的播放端連線 / max unfinished worker handshakes per IP
AUTH_FAIL_LIMIT = 5          # 同一個來源 IP 在視窗內握手失敗幾次就封鎖 / failed handshakes within the window before the IP is locked out
AUTH_FAIL_WINDOW = 600.0     # 計算失敗次數的時間視窗（秒）/ window (s) over which failures are counted
AUTH_LOCKOUT = 600.0         # 封鎖多久（秒）/ lock-out duration (s)
