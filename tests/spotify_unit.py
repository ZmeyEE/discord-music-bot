"""Spotify 帳號連結的單元測試：全部用假的 Spotify 回應（沒有 Premium 的環境無法對真的 Spotify 驗證，之後要用真帳號補驗）
Unit tests of the Spotify link with fake Spotify answers (without Premium it can't be verified against the real Spotify; to be checked later with a real account)

用 tests/run_all.py 執行 / run it with tests/run_all.py
"""
import asyncio
import base64
import hashlib
import os
import sys
import tempfile
import time
from unittest import mock
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 專案根目錄 / project root
sys.path.insert(0, ROOT)
from musicbot import params
from musicbot.hub import Hub, UserCtx
from musicbot.library import Library
from musicbot.spotify import Accounts, SpotifyError, client

res = []
def check(n, ok, d=""): res.append(bool(ok)); print(("PASS" if ok else "FAIL"), n, str(d)[:190], flush=True)
def run(coro): return asyncio.run(coro)

# ============ PKCE 與授權網址 ============
v, ch = client.new_pkce()
want = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()
check("K1 PKCE：挑戰碼是驗證碼的 SHA-256（base64url、沒有 =），驗證碼夠長", ch == want and "=" not in ch and 43 <= len(v) <= 128, (len(v), ch[:8]))
check("K2 每次都不一樣", client.new_pkce()[0] != v)
q = parse_qs(urlparse(client.auth_url("CID", "http://127.0.0.1:8765/spotify/callback", "ST", ch)).query)
check("K3 授權網址：client_id、redirect、state、S256、只讀歌單的權限", q["client_id"] == ["CID"] and q["state"] == ["ST"] and q["code_challenge_method"] == ["S256"]
      and q["redirect_uri"] == ["http://127.0.0.1:8765/spotify/callback"] and set(q["scope"][0].split()) == {"playlist-read-private", "playlist-read-collaborative"}, q)

# ============ 貼回來的網址 ============
check("R1 貼整段網址", client.parse_redirect("http://127.0.0.1:8765/spotify/callback?code=AB%2FC&state=xyz") == ("AB/C", "xyz"))
check("R2 只貼問號後面也行", client.parse_redirect("?code=abc&state=s1") == ("abc", "s1") and client.parse_redirect("code=abc&state=s1") == ("abc", "s1"))
for label, bad in (("拒絕授權", "http://127.0.0.1/cb?error=access_denied&state=s"), ("沒有授權碼", "http://127.0.0.1/cb?state=s"), ("亂貼", "你好")):
    try: client.parse_redirect(bad); ok = False
    except SpotifyError: ok = True
    check(f"R3 {label}：有明確錯誤", ok)

# ============ 歌單與歌曲的欄位（2026 年改名前後都吃）============
check("P1 歌單摘要：新欄位 items.total", client.playlist_row({"id": "a", "name": "N", "items": {"total": 7}, "images": [{"url": "u"}], "owner": {"display_name": "O"}}) == {"id": "a", "name": "N", "count": 7, "image": "u", "owner": "O"})
check("P2 歌單摘要：舊欄位 tracks.total，沒有封面也行", client.playlist_row({"id": "b", "name": "M", "tracks": {"total": 3}})["count"] == 3)
track = {"type": "track", "id": "T1", "name": "你", "duration_ms": 267000, "artists": [{"name": "鄭潤澤"}, {"name": "B"}], "album": {"images": [{"url": "big"}, {"url": "mid"}, {"url": "small"}]}}
song = client.song_from_item({"item": track})
check("S1 歌：連結、標題、長度、歌手、封面、找對應影片用的關鍵字", song == {"url": "https://open.spotify.com/track/T1", "title": "你 - 鄭潤澤, B", "duration": 267, "thumbnail": "mid", "uploader": "鄭潤澤, B", "search": "你 鄭潤澤"}, song)
check("S2 舊欄位 track 也吃", client.song_from_item({"track": track})["url"].endswith("T1"))
check("S3 影集、本機檔、已下架的略過", client.song_from_item({"item": {**track, "type": "episode"}}) is None and client.song_from_item({"item": {**track, "is_local": True}}) is None
      and client.song_from_item({"item": None}) is None and client.song_from_item({"item": {**track, "id": None}}) is None)

# ============ 分頁 ============
pages = {0: {"items": [{"id": str(i), "name": f"L{i}", "items": {"total": i}} for i in range(50)], "next": "x"}, 50: {"items": [{"id": "z", "name": "last", "items": {"total": 1}}], "next": None}}
async def fake_get(session, access, path, **kw): return pages[kw["offset"]]
with mock.patch.object(client, "get", fake_get):
    rows = run(client.list_playlists(None, "tok"))
check("G1 歌單清單：分頁讀完", len(rows) == 51 and rows[-1]["name"] == "last", len(rows))
items = [{"item": {**track, "id": f"T{i}"}} for i in range(100)]
async def fake_items(session, access, path, **kw):
    return {"items": items if kw["offset"] == 0 else [{"item": {**track, "id": "Tlast"}}, {"item": {"type": "episode"}}], "next": "x" if kw["offset"] == 0 else None}
with mock.patch.object(client, "get", fake_items):
    songs = run(client.playlist_songs(None, "tok", "pid"))
check("G2 歌單歌曲：分頁讀完、略過讀不了的", len(songs) == 101 and songs[-1]["url"].endswith("Tlast"), len(songs))
with mock.patch.object(params, "SPOTIFY_MAX_SONGS", 30), mock.patch.object(client, "get", fake_items):
    check("G3 超過匯入上限只取上限", len(run(client.playlist_songs(None, "tok", "pid"))) == 30)

# ============ 憑證存檔與授權暫存 ============
with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "sp.json")
    acc = Accounts(path)
    st = acc.begin("1", "VERIF")
    check("A1 別人拿不走授權，也不會害發起的人的授權作廢；發起的人只能用一次", acc.finish("2", st) is None and acc.finish("1", st) == "VERIF" and acc.finish("1", st) is None)
    st = acc.begin("1", "VERIF")
    check("A2 對的人、對的 state：拿回驗證碼", acc.finish("1", st) == "VERIF")
    st = acc.begin("1", "V2")
    acc.pending[st]["until"] = time.time() - 1
    check("A3 過期的授權不能用", acc.finish("1", st) is None)
    acc.link("1", {"access": "a", "refresh": "r", "expires": 1}, "小明")
    check("A4 連結後寫進檔案，重新讀回來還在", Accounts(path).users["1"]["refresh"] == "r" and os.path.exists(path) and not os.path.exists(path + ".tmp"))
    check("A5 登出就刪掉", acc.unlink("1") and "1" not in Accounts(path).users and not acc.unlink("1"))
    with open(path, "w", encoding="utf-8") as f: f.write("{壞掉")
    check("A6 檔案壞掉不會讓機器人起不來", Accounts(path).users == {})

# ============ 網頁操作（走真的 Hub，Spotify 用假的）============
async def flows(tmp):
    os.environ["SPOTIFY_CLIENT_ID"] = "CID"
    hub = Hub()
    hub.spotify, hub.library = Accounts(os.path.join(tmp, "s.json")), Library(os.path.join(tmp, "l.json"))
    me, other = UserCtx(user_id=111, name="小明", via="link"), UserCtx(user_id=222, name="小華", via="link")
    out = {}
    note, reply = await hub.spotify_action(me, {"type": "sp_status"})
    out["status0"] = reply["data"]
    note, reply = await hub.spotify_action(me, {"type": "sp_connect"})
    url = reply["data"]["auth_url"]; state = parse_qs(urlparse(url).query)["state"][0]
    out["url"] = url
    async def fake_exchange(session, cid, redirect, code, verifier): return {"access": "A1", "refresh": "R1", "expires": time.time() + 3600}
    async def fake_get1(session, access, path, **kw): return {"display_name": "小明的 Spotify"}
    with mock.patch.object(client, "exchange", fake_exchange), mock.patch.object(client, "get", fake_get1):
        n2, r2 = await hub.spotify_action(other, {"type": "sp_finish", "text": f"http://127.0.0.1:8765/spotify/callback?code=C&state={state}"})
        out["stolen"] = (n2, r2["data"]["linked"])
        n3, r3 = await hub.spotify_action(me, {"type": "sp_finish", "text": f"http://127.0.0.1:8765/spotify/callback?code=C&state={state}"})
        out["linked"] = (n3, r3["data"])
        n4, r4 = await hub.spotify_action(me, {"type": "sp_finish", "text": f"?code=C&state={state}"})
        out["reuse"] = (n4, r4["data"]["linked"])
    out["file"] = Accounts(os.path.join(tmp, "s.json")).users.get("111", {}).get("refresh")
    async def fake_list(session, access): return [{"id": "p1", "name": "我的最愛", "count": 2, "image": "", "owner": "我"}]
    with mock.patch.object(client, "list_playlists", fake_list):
        n5, r5 = await hub.spotify_action(me, {"type": "sp_playlists"})
        out["lists"] = r5["data"]["playlists"]
        n6, r6 = await hub.spotify_action(other, {"type": "sp_playlists"})
        out["other_lists"] = (n6, "playlists" in r6["data"])
    async def fake_songs(session, access, pid): return [song, {**song, "url": "https://open.spotify.com/track/T2", "title": "二"}]
    with mock.patch.object(client, "playlist_songs", fake_songs):
        n7, r7 = await hub.spotify_action(me, {"type": "sp_import", "id": "p1", "name": "我的最愛"})
        out["import"] = (n7, r7["type"], [c["name"] for c in r7["data"]["tree"]["children"]], r7["data"]["tree"]["count"])
    # 憑證過期：先續期再呼叫 / an expired access token is refreshed first
    hub.spotify.users["111"]["expires"] = 0
    calls = []
    async def fake_refresh(session, cid, rt): calls.append(rt); return {"access": "A2", "refresh": rt, "expires": time.time() + 3600}
    async def fake_list2(session, access): calls.append(access); return []
    with mock.patch.object(client, "refresh", fake_refresh), mock.patch.object(client, "list_playlists", fake_list2):
        await hub.spotify_action(me, {"type": "sp_playlists"})
    out["refresh"] = calls
    # 401：續期後再試一次 / on a 401 refresh and try once more
    seq = []
    async def flaky(session, access):
        seq.append(access)
        if access == "A2": raise SpotifyError("expired")
        return []
    async def fake_refresh2(session, cid, rt): return {"access": "A3", "refresh": rt, "expires": time.time() + 3600}
    with mock.patch.object(client, "refresh", fake_refresh2), mock.patch.object(client, "list_playlists", flaky):
        await hub.spotify_action(me, {"type": "sp_playlists"})
    out["retry"] = seq
    n8, r8 = await hub.spotify_action(me, {"type": "sp_logout"})
    out["logout"] = (r8["data"]["linked"], Accounts(os.path.join(tmp, "s.json")).users.get("111"))
    os.environ.pop("SPOTIFY_CLIENT_ID")
    n9, r9 = await hub.spotify_action(me, {"type": "sp_connect"})
    out["unconfigured"] = (n9, r9["data"]["enabled"])
    n10, _ = await hub.spotify_action(UserCtx(user_id=None, name="x", pending=True), {"type": "sp_status"})
    out["noid"] = n10
    # 在看板上貼 Client ID（只有擁有者）/ pasting the Client ID on the dashboard (owner only)
    from musicbot import config
    config.SETTINGS_FILE = type(config.SETTINGS_FILE)(os.path.join(tmp, "settings.json")); config._settings.clear()
    boss = UserCtx(user_id=111, name="小明", via="link", is_owner=True)
    out["setup_guest"] = await hub.spotify_action(me, {"type": "sp_setup", "client_id": "a" * 32})
    out["setup_bad"] = await hub.spotify_action(boss, {"type": "sp_setup", "client_id": "not-an-id"})
    out["setup_ok"] = await hub.spotify_action(boss, {"type": "sp_setup", "client_id": "A1" * 16})
    out["setup_after"] = (hub.spotify_client_id(), (await hub.spotify_action(me, {"type": "sp_status"}))[1]["data"], (await hub.spotify_action(boss, {"type": "sp_status"}))[1]["data"])
    out["setup_file"] = config.get_setting("spotify_client_id")
    os.environ["SPOTIFY_CLIENT_ID"] = "FROMENV"
    out["setup_env_first"] = hub.spotify_client_id()
    os.environ.pop("SPOTIFY_CLIENT_ID")
    await hub.spotify_action(boss, {"type": "sp_setup", "client_id": ""})
    out["setup_clear"] = hub.spotify_client_id()
    return out

with tempfile.TemporaryDirectory() as d:
    o = run(flows(d))
check("H1 還沒連結：狀態是已設定、未連結，並帶著要登記的 redirect 網址", o["status0"]["enabled"] and not o["status0"]["linked"] and o["status0"]["redirect"].startswith("http://127.0.0.1:"), o["status0"])
check("H2 按前往授權：給出 Spotify 的授權網址（帶 PKCE）", o["url"].startswith("https://accounts.spotify.com/authorize?") and "code_challenge=" in o["url"])
check("H3 別人貼不走我的授權", o["stolen"][1] is False and "過期或不是你發起" in o["stolen"][0], o["stolen"])
check("H4 貼回網址：連結成功，顯示 Spotify 暱稱", o["linked"][1]["linked"] and o["linked"][1]["name"] == "小明的 Spotify" and "已連結" in o["linked"][0], o["linked"])
check("H5 同一份授權不能重複使用", o["reuse"][1] is True and "過期" in o["reuse"][0], o["reuse"])
check("H6 憑證寫進檔案，而且網頁拿到的狀態裡沒有任何憑證", o["file"] == "R1" and not any(k in json_str for json_str in [str(o["linked"][1])] for k in ("R1", "A1", "refresh", "access")))
check("H7 列出自己的歌單", o["lists"][0]["name"] == "我的最愛", o["lists"])
check("H8 沒連結的人列不出歌單", o["other_lists"] == ("還沒連結 Spotify 帳號", False), o["other_lists"])
check("H9 匯入：存成我的歌單（2 首），回新的歌單樹", o["import"][0].startswith("已存成歌單") and o["import"][1] == "library" and o["import"][2] == ["我的最愛"] and o["import"][3] == 2, o["import"])
check("H10 access token 過期：先續期再呼叫", o["refresh"] == ["R1", "A2"], o["refresh"])
check("H11 呼叫時被 401：續期後再試一次", o["retry"] == ["A2", "A3"], o["retry"])
check("H12 登出：狀態變未連結，檔案裡的憑證也刪了", o["logout"] == (False, None), o["logout"])
check("H13 沒設定 SPOTIFY_CLIENT_ID：明確說沒設定", "SPOTIFY_CLIENT_ID" in o["unconfigured"][0] and o["unconfigured"][1] is False, o["unconfigured"])
check("H14 沒有身分的人不能用", "/help" in (o["noid"] or ""), o["noid"])

check("H15 不是擁有者不能設定 Client ID", "擁有者" in o["setup_guest"][0] and not o["setup_guest"][1]["data"]["enabled"], o["setup_guest"])
check("H16 Client ID 格式不對會被擋下來", "32" in o["setup_bad"][0] and not o["setup_bad"][1]["data"]["enabled"], o["setup_bad"])
check("H17 擁有者貼上正確的 Client ID：存起來、立刻可以連結", "已儲存" in o["setup_ok"][0] and o["setup_ok"][1]["data"]["enabled"] and o["setup_file"] == "a1" * 16, o["setup_ok"])
check("H18 只有擁有者的畫面會出現貼 Client ID 的欄位", o["setup_after"][1]["can_setup"] is False and o["setup_after"][2]["can_setup"] is True, o["setup_after"][1:])
check("H19 .env 有設定時以 .env 為主；清除後回到沒設定", o["setup_env_first"] == "FROMENV" and o["setup_clear"] == "", (o["setup_env_first"], o["setup_clear"]))

print(f"{sum(res)}/{len(res)} 通過", flush=True)
sys.exit(0 if all(res) else 1)
