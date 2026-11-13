# 測試 / Tests

回歸測試，用來確認改了程式之後，原本的功能沒有壞掉
Regression tests, to make sure old features still work after you change something

## 怎麼跑 / How to run

從專案根目錄 / from the project root:

```bash
.venv\Scripts\python.exe tests\run_all.py            # 全部 / everything
.venv\Scripts\python.exe tests\run_all.py verify     # 只跑名稱含 verify 的 / only suites matching "verify"
.venv\Scripts\python.exe tests\run_relay.py          # 中繼站 / relay suites
```

需要 / Needs:
- 已安裝 `requirements.txt` 的套件、ffmpeg / the packages from `requirements.txt` and ffmpeg
- **網路**：測試會解析一支 Bilibili 影片（`av55185686`）/ **network access**: the tests resolve one Bilibili video (`av55185686`)
- 埠 8766、8767、8770、8791 沒被占用 / ports 8766, 8767, 8770 and 8791 are free

不會動到你正式的 `settings.json`、`members.json`（測試用的檔案是 `settings_test.json`、`members_test.json`，已列入 `.gitignore`）
Your real `settings.json` and `members.json` are never touched (tests use `settings_test.json` and `members_test.json`, both in `.gitignore`)

## 怎麼運作 / How it works

`harness_hub.py` 啟動**真的** `Hub`、`Dashboard`、`PlayerBot`，只把 Discord 語音層換成假的（`FakeVC`、`FakeChannel`、`FakeGuild`）
它有 3 個播放器、4 個語音頻道、幾位假使用者，還開一個除錯埠 8767 讓測試移動使用者、發憑證、注入卡頓
`harness_hub.py` starts the **real** `Hub`, `Dashboard` and `PlayerBot` and only replaces the Discord voice layer with fakes; it has 3 players, 4 voice channels, a few fake users and a debug port (8767) so tests can move users, issue tokens and inject stutter

## 套件 / Suites

| 腳本 / Script | 模式 / Mode | 測什麼 / What it checks |
| --- | --- | --- |
| `hub_test.py` | voice | 語音模式的權限、多頻道、分身預約 / voice-mode permissions, multi-channel, clone reservation |
| `open_test.py` | open | 開放模式、加歌／刪除／排序／循環 / open mode, add / remove / reorder / loop |
| `loop_test.py` | open | 單曲與列表循環、刪除正在播放的 / single and queue loop, deleting the current track |
| `seek_test.py` | open | 拖曳進度條跳轉 / seeking with the progress bar |
| `quality_test.py` | open | 切換音質與實際位元率 / quality switch and the real bitrate |
| `verify_test.py` | verify | 專屬連結、裝置憑證、撤銷、退出伺服器 / personal links, device tokens, revoke, leaving the server |
| `health_test.py` | open | 卡頓偵測與從最後加入的頻道開始停止 / stutter detection and stopping the newest channel first |
| `avatar_test.py` | verify | 點歌者頭像 / requester avatars |
| `health_unit.py` | 獨立 / standalone | 卡頓偵測的單元測試（假時間）/ unit tests for the stutter detector (fake time) |
| `harden_test.py` | 獨立 / standalone | 中繼站加固：路徑穿越、限流、握手封鎖 / relay hardening: path traversal, rate limits, handshake lock-out |
| `relay_test.py` `relay_verify.py` `relay_extra.py` | relay | 經過中繼站的整條路：轉送、權限、斷線與自動恢復 / the full path through the relay: forwarding, permissions, offline and auto-recovery |

## 寫新測試 / Writing a new test

1. 在 `tests/` 新增 `xxx_test.py`，用 `check(名稱, 條件, 細節)` 記錄結果，最後印出 `N/M 通過`（執行器靠這行判斷）
   Add `xxx_test.py`, record results with `check(name, ok, detail)` and print `N/M 通過` at the end (the runner reads that line)
2. 把它登記到 `run_all.py` 的 `SUITES`（要 harness 的）或 `STANDALONE`
   Register it in `SUITES` (needs the harness) or `STANDALONE` in `run_all.py`
3. 測試裡不要放任何真的 Token、ID 或個人資料 / no real tokens, IDs or personal data in tests
