"""測試用的假環境：真的 Hub / Dashboard / PlayerBot，只把 Discord 語音層換成假的
模擬 1 個主 bot + N-1 個分身，伺服器有多個語音頻道、多位使用者（可用 debug 埠 8767 移動他們、發憑證、注入卡頓）
需要 ffmpeg（在 PATH，或用環境變數 FFMPEG_PATH 指定）

Fake environment for the tests: the real Hub / Dashboard / PlayerBot, only the Discord voice layer is faked.
Simulates 1 main bot + N-1 clones, a server with several voice channels and a few users
(move them, issue tokens and inject stutter through the debug port 8767).
Needs ffmpeg (on PATH, or set the FFMPEG_PATH environment variable).

通常由 run_all.py / run_relay.py 啟動，不用自己跑 / normally started by run_all.py / run_relay.py, you don't run it by hand
"""
import asyncio, os, sys, types, json, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 專案根目錄 / project root
sys.path.insert(0, ROOT)
import discord
from aiohttp import web
from musicbot import config
from musicbot.hub import Hub
from musicbot.player import PlayerBot
from musicbot.dashboard import Dashboard

FAKE_SECS = int(os.environ.get("FAKE_SECS", "900"))
N_WORKERS = int(os.environ.get("N_WORKERS", "3"))
GID = 777
OWNER = 9001                      # 機器人擁有者
USERS = {1001: "小明", 1002: "小華", 1003: "小美(不在語音)", 1004: "阿傑", 9001: "擁有者"}
CHANNELS = {501: "放鬆休息", 502: "肝到世界盡頭", 503: "趕工阿", 504: "會議室"}
discord.FFmpegOpusAudio = lambda *a, **k: object()


SENT = []        # 偵測器公告到各語音頻道聊天室的訊息（頻道名, 內容）

class FakeMember:
    def __init__(self, uid): self.id = uid; self.bot = False

class FakeVC:
    def __init__(self, guild, channel):
        self.guild, self.channel = guild, channel
        self.playing = self.paused = False; self.after = None; self.timer = None; self.latency = 0.03
        self._connection = types.SimpleNamespace(dave_session=None, dave_protocol_version=0)
    def is_connected(self): return True
    def is_playing(self): return self.playing and not self.paused
    def is_paused(self): return self.paused
    def play(self, src, after=None):
        self.playing, self.paused, self.after = True, False, after
        self.timer = asyncio.get_running_loop().call_later(FAKE_SECS, self._finish)
    def _finish(self):
        self.playing = False; a, self.after = self.after, None
        if a: a(None)
    def stop(self):
        if self.timer: self.timer.cancel()
        was = self.playing; self.playing = self.paused = False
        a, self.after = self.after, None
        if was and a: a(None)
    def pause(self): self.paused = True
    def resume(self): self.paused = False
    async def move_to(self, ch): self.channel = ch
    async def disconnect(self): self.guild.voice_client = None

class FakeChannel:
    def __init__(self, guild, cid, name):
        self.guild, self.id, self.name, self.bitrate, self.members = guild, cid, name, 64000, []
    async def connect(self):
        self.guild.voice_client = FakeVC(self.guild, self); return self.guild.voice_client
    async def send(self, text):
        SENT.append((self.name, text))

class FakeGuild:
    def __init__(self, gid, name):
        self.id, self.name, self.voice_client = gid, name, None
        self.chans = {cid: FakeChannel(self, cid, n) for cid, n in CHANNELS.items()}
        self.stage_channels = []
    @property
    def voice_channels(self): return list(self.chans.values())
    def get_channel(self, cid): return self.chans.get(cid)
    @property
    def me(self): return None
    async def fetch_member(self, uid):
        """模擬 REST 查成員：USERS 裡的人是成員，其他人（例如 4040）已經不在伺服器"""
        if uid in USERS:
            def _url(size, u=uid):
                if os.environ.get("AV_DATA"):   # 目視測試：用內嵌圖片代替 Discord CDN
                    col = ["%23e0a3b4", "%237fa6d6", "%23f0c77e", "%2394c9b0"][u % 4]
                    return f"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><rect width='64' height='64' fill='{col}'/><circle cx='32' cy='26' r='12' fill='white'/><ellipse cx='32' cy='56' rx='20' ry='14' fill='white'/></svg>"
                return f"https://cdn.discordapp.com/avatars/{u}/abc.png?size={size}"
            av = types.SimpleNamespace(with_size=lambda size: types.SimpleNamespace(url=_url(size)))
            return types.SimpleNamespace(id=uid, display_name=USERS[uid], display_avatar=av)
        raise discord.NotFound(types.SimpleNamespace(status=404, reason="Not Found"), "Unknown Member")


async def main():
    # 測試用的設定檔：不碰正式的 settings.json / use a throwaway settings file, never the real settings.json
    config.SETTINGS_FILE = type(config.SETTINGS_FILE)(os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings_test.json"))
    if config.SETTINGS_FILE.exists() and os.environ.get("KEEP_SETTINGS") != "1": config.SETTINGS_FILE.unlink()
    config.load_settings()
    hub = Hub(); hub.owner_ids = {OWNER}
    from musicbot.members import Registry
    MEMBERS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "members_test.json")
    if os.environ.get("KEEP_MEMBERS") != "1" and os.path.exists(MEMBERS_PATH): os.remove(MEMBERS_PATH)
    hub.members = Registry(MEMBERS_PATH)           # 測試專用的成員登錄檔（不碰正式的 members.json）
    from musicbot.library import Library
    LIB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "library_test.json")
    if os.path.exists(LIB_PATH): os.remove(LIB_PATH)
    hub.library = Library(LIB_PATH)                # 測試專用的歌單檔（不碰正式的 library.json）/ a throwaway library file (never the real library.json)
    if os.environ.get("FAKE_SPOTIFY"):             # 假的 Spotify：不連網，帳號固定叫"測試帳號" / a fake Spotify: no network, the account is always "測試帳號"
        from musicbot.spotify import Accounts, client as spc
        SP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "spotify_test.json")
        if os.path.exists(SP_PATH): os.remove(SP_PATH)
        hub.spotify = Accounts(SP_PATH)
        async def _exchange(*a, **k): return {"access": "A", "refresh": "R", "expires": time.time() + 3600}
        async def _get(session, access, path, **kw): return {"display_name": "測試帳號"}
        async def _lists(session, access): return [{"id": "p1", "name": "Spotify 最愛", "count": 3, "image": "", "owner": "我"}]
        async def _songs(session, access, pid): return [{"url": f"https://open.spotify.com/track/T{i}", "title": f"S{i} - 歌手", "duration": 200, "thumbnail": "", "uploader": "歌手", "search": f"S{i} 歌手"} for i in range(3)]
        spc.exchange, spc.get, spc.list_playlists, spc.playlist_songs = _exchange, _get, _lists, _songs
    loop = asyncio.get_running_loop()
    guilds = {}
    hub.workers = []
    for i in range(N_WORKERS):
        w = PlayerBot(hub, i); w.loop = loop
        g = FakeGuild(GID, "測試伺服器"); guilds[i] = g
        w._connection.user = types.SimpleNamespace(id=5000 + i, name=("主機器人" if i == 0 else f"分身{i}"))
        w.get_guild = (lambda gid, g=g: g if gid == GID else None)
        w._fake_guild = g
        hub.workers.append(w)
    PlayerBot.guilds = property(lambda self: [self._fake_guild])
    hub.base_url = "http://localhost:8766"
    hub.dashboard = Dashboard(hub, os.path.join(ROOT, "web"), "127.0.0.1", 8766)
    await hub.dashboard.start()
    if os.environ.get('RELAY_URL'):
        from musicbot.relay_client import RelayClient
        asyncio.create_task(RelayClient(hub, os.environ['RELAY_URL'], os.environ['RELAY_KEY']).run())

    def place(uid, cid):               # 把使用者放進某頻道（cid=None 代表不在語音）
        for ch in guilds[0].chans.values():
            ch.members = [m for m in ch.members if m.id != uid]
        if cid: guilds[0].chans[cid].members.append(FakeMember(uid))

    place(1001, 501); place(1002, 502); place(1004, 503)   # 1003 不在語音；9001 先不在
    hub.workers[0].state(GID).last_voice_id = 501

    # ---- debug 埠：讓測試腳本移動使用者、取憑證 ----
    async def move(req):
        uid = int(req.query["u"]); cid = req.query.get("ch"); place(uid, int(cid) if cid else None)
        for w in hub.workers: hub.notify(GID)
        return web.json_response({"ok": True})
    async def token(req):
        uid = int(req.query["u"]); ttl = int(req.query.get("ttl", 43200))
        from musicbot import auth
        gid = int(req.query.get("g", GID))
        return web.json_response({"t": auth.make_token(hub.secret, gid, uid, USERS.get(uid, "?"), ttl)})
    async def info(req):
        return web.json_response({"workers": [{"pid": w.pid, "vc": (g.voice_client.channel.id if g.voice_client else None)} for w, g in zip(hub.workers, guilds.values())]})
    # ---- 驗證相關的除錯入口（模擬使用者在 Discord 輸入 /verify、被撤銷、機器人重啟）----
    async def revoke(req):
        return web.json_response({"n": hub.revoke_user(int(req.query["u"]))})
    async def regdevice(req):    # 直接替某人登記一個裝置（用來測"已退出伺服器的人"）
        uid = int(req.query["u"]); return web.json_response({"d": hub.members.add_device(uid, "舊名字", GID)})
    async def restart_registry(req):   # 模擬"機器人重啟"：重新從檔案載入成員登錄
        hub.members = Registry(MEMBERS_PATH); return web.json_response({"devices": len(hub.members.devices)})
    async def registry_file(req):
        raw = open(MEMBERS_PATH, encoding="utf-8").read() if os.path.exists(MEMBERS_PATH) else ""
        return web.json_response({"raw": raw})
    # ---- 卡頓偵測：注入假的卡頓事件，再手動跑一次偵測 ----
    from musicbot.health import HealthMonitor, StreamProbe
    import time as _t
    monitor = HealthMonitor(hub); monitor.cpu.percent = lambda: float(os.environ.get("FAKE_CPU", "10"))
    clock = {"now": 10000.0}          # 假時鐘：每個 tick = 5 秒，不用真的等
    async def tick(req):              # /tick?n=14&w=0,1&ev=1：跑 n 個 5 秒區間（w 的播放器每區間注入 ev 次卡頓）；有結論就套用並停止
        n = int(req.query.get("n", 1)); ev = int(req.query.get("ev", 0))
        ws_ = [int(x) for x in req.query.get("w", "").split(",") if x]
        removed, done = None, 0
        for _ in range(n):
            for i in ws_:
                st = hub.workers[i].state(GID)
                if st.probe is not None: st.probe.count += ev
            clock["now"] += 5; done += 1
            r = monitor.check(now=clock["now"], lag=float(req.query.get("lag", 0)))
            if r:
                removed = {"label": r.sample.label, "channel": r.sample.channel, "remaining": r.remaining, "reasons": r.reasons,
                           "base": r.evidence.base_seconds if r.evidence else None, "events": r.evidence.recent_events if r.evidence else None}
                await hub.remove_stream(r)
                break
        return web.json_response({"removed": removed, "ticks": done, "limit": hub.stream_limit, "streaming": hub.streaming_now(),
                                  "sent": SENT[-8:], "k": monitor.ledger.k})
    async def shutdown(req):          # 讓測試腳本能乾淨地關掉 harness（不分作業系統）/ lets a test stop the harness on any OS
        asyncio.get_running_loop().call_later(0.2, os._exit, 0); return web.json_response({"ok": True})
    async def expire_hold(req):
        hub._ceiling_until = 0.0; hub._notify_all()
        return web.json_response({"limit": hub.stream_limit})
    async def fill(req):              # /fill?n=5000：直接在第一個播放器塞 n 首假曲目（測大清單的效能）/ put n fake tracks into the first player (large-queue performance tests)
        from musicbot.sources import Track
        n = int(req.query.get("n", 1000)); st = hub.workers[0].state(GID)
        if req.query.get("clear"): st.queue.clear()      # clear=1：先清空再放 / clear=1: empty the queue first
        st.queue.extend(Track(url=f"https://www.bilibili.com/video/BV1xx{i:07d}", title=f"測試曲目 {i:04d} - 某某歌手 官方版 MV", requester="小明",
                              duration=180 + i % 120, uploader="上傳者", enriched=True) for i in range(n))
        hub.notify(GID)
        return web.json_response({"queue": len(st.queue)})
    async def libseed(req):           # /libseed?u=1001&n=30&name=x：替這個人的歌單放一張有 n 首歌（含縮圖，不會去網路補資料）的歌單 / put a playlist of n songs (with thumbnails, nothing to enrich online) into this person's library
        from musicbot.library import tree
        u, n = req.query["u"], int(req.query.get("n", 30))
        root = hub.library.root(u)
        if req.query.get("reset"): root["children"].clear()
        songs = [{"url": f"https://www.bilibili.com/video/BV1yy{i:07d}", "title": f"{req.query.get('name', '歌')} {i:03d}", "duration": 200, "thumbnail": f"https://i0.hdslb.com/x{i}.jpg", "uploader": "上傳者"} for i in range(n)]
        node = tree.add_playlist(root, req.query.get("parent", "root"), req.query.get("name", "種子歌單"), songs)
        return web.json_response({"id": node["id"], "tree": tree.outline(root)})
    async def libfile(req):           # /libfile?u=1003：磁碟上這個人的歌單檔實際存了什麼 / what is really stored on disk for this person
        from musicbot.library import Library, tree
        root = Library(LIB_PATH).root(req.query["u"])
        return web.json_response({"playlists": sum(1 for n in tree.walk(root) if n["type"] == "playlist"), "songs": tree.count_songs(root)})
    async def scope_of(req):          # /scope_of：第一個播放器目前的資料夾循環狀態 / the first player's current folder-loop state
        sc = hub.workers[0].state(GID).scope
        return web.json_response(None if sc is None else {"mode": sc["mode"], "node": sc["node"]})
    async def scope_test(req):        # /scope_test?u=1003：直接問 hub 資料夾循環下一輪放什麼 / ask the hub directly what a folder loop adds next
        from musicbot.library import tree
        user = req.query["u"]; root = hub.library.root(user)
        for kid in list(root["children"]): root["children"].remove(kid)
        folders = []
        for name in "ABC":
            f = tree.add_folder(root, "root", name)
            tree.add_playlist(root, f["id"], name.lower(), [{"url": f"https://x/{name}1", "title": name + "1"}, {"url": f"https://x/{name}2", "title": name + "2"}])
            folders.append(f)
        one = {"mode": "folder", "user": user, "node": folders[0]["id"]}
        again = [s["title"] for s in hub.library_refill(one)]
        loop = {"mode": "folders", "user": user, "node": folders[0]["id"]}
        order = ["".join(s["title"][0] for s in hub.library_refill(loop)[:1]) for _ in range(5)]
        tree.delete(root, [folders[0]["id"]])
        return web.json_response({"folder": {"same": again == ["A1", "A2"] and one["node"] == folders[0]["id"]},
                                  "folders": {"order": order, "expect": ["B", "C", "A", "B", "C"]},
                                  "gone": hub.library_refill({"mode": "folder", "user": user, "node": folders[0]["id"]})})
    async def poke(req):              # /poke?n=20：連續通知 n 次狀態改變（模擬有人進出頻道、補縮圖…）/ n state-change notifications in a row (people joining, thumbnails arriving...)
        for _ in range(int(req.query.get("n", 1))):
            hub.notify(GID); await asyncio.sleep(float(req.query.get("gap", 0.1)))
        return web.json_response({"ok": True})
    dbg = web.Application(); dbg.add_routes([web.get("/tick", tick), web.get("/fill", fill), web.get("/poke", poke), web.get("/libfile", libfile), web.get("/scope_of", scope_of), web.get("/scope_test", scope_test), web.get("/libseed", libseed), web.get("/expire_hold", expire_hold), web.get("/shutdown", shutdown), web.get("/move", move), web.get("/token", token), web.get("/info", info),
        web.get("/revoke", revoke), web.get("/regdevice", regdevice),
        web.get("/restart_registry", restart_registry), web.get("/registry_file", registry_file)])
    r = web.AppRunner(dbg); await r.setup(); await web.TCPSite(r, "127.0.0.1", 8767).start()
    print("READY", flush=True)
    await asyncio.Event().wait()

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
asyncio.run(main())



