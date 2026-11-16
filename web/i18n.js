/* ===========================================================================
   多語言（原生 JS）/ i18n (vanilla JS)
   - 預設繁體中文，右上角選單可換，選擇存在這個瀏覽器，換完會重新整理
   - 加新語言：在 LANGS 加一行，再照 "zh-TW" 那一組把每個 key 翻過去，缺的 key 會自動用繁體中文
   - 這裡只管網頁介面，Discord 訊息和伺服器傳來的提示還是繁體中文

   - Default is Traditional Chinese. The menu at the top right switches it, the choice is kept in this browser, the page reloads after a change.
   - To add a language: add a line to LANGS, then translate every key of the "zh-TW" block. Missing keys fall back to Traditional Chinese.
   - This only covers the web dashboard. Discord messages and notices sent by the server stay in Traditional Chinese.

   HTML 標記 / HTML attributes:
     data-i18n="key"        -> textContent        data-i18n-html="key" -> innerHTML (only for our own strings)
     data-i18n-title / -aria / -ph / -alt  ->  title / aria-label / placeholder / alt
   JS: T("key", { name: "x" }) 把 {name} 換成 x / replaces {name} with x
   =========================================================================== */
(function () {
  const LANGS = [["zh-TW", "繁體中文"], ["zh-CN", "简体中文"], ["en", "English"], ["ja", "日本語"]];
  const HTML_LANG = { "zh-TW": "zh-Hant", "zh-CN": "zh-Hans", en: "en", ja: "ja" };

  const D = {
    "zh-TW": {
      title: "音樂看板", brand: "音樂看板", connecting: "連線中…",
      quality: "音質", qualityAria: "音質（Opus 位元率）",
      q128: "標準：128 kbps（約 16 KB/s）", q192: "高：192 kbps（預設）", q256: "極高：256 kbps",
      q320: "最高：320 kbps（約 40 KB/s）", q510: "Opus 規格上限：510 kbps（搭配無損來源時用）",
      loopAria: "循環模式", loopOff: "不循環", loopOffTip: "播完就換下一首",
      loopOne: "單曲循環", loopOneTip: "一直重複目前這首", loopQueue: "列表循環", loopQueueTip: "播完的歌排到清單最後",
      playersAria: "播放器", nowPlaying: "正在播放", dropHint: "把待播卡片拖到這裡，立即播放",
      biliAccount: "Bilibili 帳號", queueTitle: "待播清單", shuffle: "隨機打亂順序", clearList: "清空待播清單",
      clearAgain: "再按一次清空", emptyTitle: "清單是空的", emptySub: "在下方貼上網址，或在 Discord 使用 /play",
      queueMore: "只畫出前 {shown} 首，後面還有 {more} 首（照順序會播到）",
      queueScroll: "已載入 {shown}／{total} 首，往下捲載入更多",
      queueAria: "待播卡片，可拖曳調整順序", addAria: "歌曲網址或關鍵字",
      addPh: "貼上 Bilibili／YouTube／Spotify 網址、BV 號，或輸入關鍵字",
      nextTip: "插到最前面，這首播完就換它（Shift+Enter）", next: "下一首", addTip: "加到清單最後（Enter）", add: "加入",
      trashTitle: "刪除區", trashHint: "拖到這裡放開<br>即可刪除", close: "關閉", biliQrAlt: "Bilibili 登入 QR 碼",
      biliScan: "請用 Bilibili App 掃描", logout: "登出", scanLogin: "掃碼登入",
      verifyTitle: "請從 Discord 的專屬連結進來",
      verifyStep1: "在這個伺服器的任何文字頻道輸入 <code>/help</code>",
      verifyStep2: "點機器人回你的「<b>點此開啟看板</b>」",
      verifySub: "點一下就自動確認你的 Discord 身分、顯示你的暱稱，並記住這個瀏覽器，之後直接開這個網址就能進來。<br>連結只有你看得到，12 小時有效，請勿轉貼。",
      invalidTitle: "連結無效或已過期",
      invalidBody: "請回到 Discord，輸入 <code>/help</code> 取得你專屬的新連結。<br>連結 12 小時有效，且只能給本人使用。",
      pickServer: "選擇伺服器", noGuild: "機器人還沒加入任何伺服器。",
      detectBili: "辨識為：Bilibili 連結", detectYt: "辨識為：YouTube 連結", detectSpotify: "辨識為：Spotify 連結（會去找對應的歌來播）",
      detectUrlHost: "辨識為：網址（{host}）", detectUrl: "辨識為：網址", detectBV: "辨識為：Bilibili BV 號",
      detectAv: "辨識為：Bilibili av 號", detectYtSearch: "辨識為：YouTube 關鍵字搜尋", detectBiliSearch: "辨識為：Bilibili 關鍵字搜尋",
      emptyChannelToast: "這個頻道還沒有開始播放：先在下面貼上網址加一首歌，機器人就會進去",
      requestedBy: "點歌：{name}", requester: "點歌", playNow: "立即播放", remove: "刪除",
      resume: "繼續播放", pause: "暫停", nothingPlaying: "目前沒有在播放",
      tabTitlePlaying: "播放中 · {title} · ", emptyTabStatus: "「{channel}」還沒有開始播放 — 在下面貼上網址，機器人就會進去",
      connectedTo: "已連線 · {channel}", notInVoice: "機器人尚未進入語音頻道 — 請在 Discord 使用 /join 或 /play",
      loading: "載入中…", sourceChip: "來源 {quality} → Opus {bitrate} kbps", stopLeave: "停止並離開語音頻道", seekAria: "播放進度",
      keyTip: "Enter 加到最後 · Shift+Enter 下一首 · 在頁面任何地方 Ctrl+V 貼上也行",
      resolvingEnd: "解析中，卡片稍後出現…", resolvingNext: "解析中，這首會插到最前面…", pasted: "已貼上，解析中…",
      dropped: "已加入拖進來的連結，解析中…", yourChannel: "你所在的頻道", addToChannel: "＋ 加到頻道",
      freshTabTip: "「{name}」還沒有開始播放：貼上網址加一首歌，機器人就會進去，而且不會影響其他頻道",
      notPlayingYet: "尚未播放", closeTab: "關閉這個分頁", closeTabNamed: "關閉「{name}」分頁",
      addToChannelTip: "選一個還沒有播放器的語音頻道，會開成一個獨立的分頁（派一個閒置的機器人進去，不影響其他頻道）",
      members: "{n} 人", nobody: "沒人", playersUsed: "播放器 {used}／{total} 使用中", pickChannelFirst: "還沒有在播放：先選一個語音頻道",
      stutterCap: "偵測到卡頓，同時播放上限已降為 {n} 個頻道", idleClones: "還有 {n} 個閒置，可接手新的頻道",
      allBusy: "全部使用中。要同時在更多頻道播放，需要再設定分身（見 README）",
      inVoiceOnly: "人在語音頻道裡", readonly: "唯讀", joinFirst: "先加入語音頻道，才能加歌",
      pasteTo: "貼上網址，加到「{name}」（只會進這個頻道）", thisChannel: "這個頻道",
      biliLoggedOut: "未登入 Bilibili", biliSwap: "{vip}　點此更換帳號", biliClickScan: "點此掃碼登入",
      biliSwapBtn: "更換帳號（掃碼）", biliNote1: "<b>一般會員的音質上限與未登入相同</b>（約 192 kbps AAC）。Hi-Res 無損與杜比是<b>大會員</b>專屬。",
      biliNote2: "<b>大會員</b>：機器人會優先使用 Hi-Res 無損（FLAC）音軌，搭配 Opus 320～510 kbps 最接近原音。",
      biliNote3: "登入後的主要好處：降低搜尋被限流（HTTP 412）的機率、能播放需要登入才能看的影片。",
      biliNote4: "掃碼是 Bilibili 官方的登入流程，機器人不會接觸你的密碼；登入憑證只存在<b>執行機器人的這台電腦</b>，重開機器人仍會記住。",
      qrScanLeft: "請用 Bilibili App 掃描（{n} 秒後過期）", qrFetching: "正在向 Bilibili 取得 QR 碼…",
      qrScanned: "已掃描，請在手機上按「確認登入」", qrExpired: "QR 碼已過期，請重新產生", qrRegen: "重新產生 QR 碼",
      loginFailed: "登入失敗", retry: "再試一次", loginOk: "登入成功：{name}",
      guest: "訪客", guestN: "訪客{n}", verified: "已確認身分：{name}，這個瀏覽器會被記住",
      revoked: "你的裝置已被撤銷，請重新用 /help 的連結進來", workerOffline: "播放端離線", reconnecting: "連線中斷，重新連線中…",
    },

    "zh-CN": {
      title: "音乐看板", brand: "音乐看板", connecting: "连接中…",
      quality: "音质", qualityAria: "音质（Opus 比特率）",
      q128: "标准：128 kbps（约 16 KB/s）", q192: "高：192 kbps（默认）", q256: "极高：256 kbps",
      q320: "最高：320 kbps（约 40 KB/s）", q510: "Opus 规格上限：510 kbps（搭配无损音源时用）",
      loopAria: "循环模式", loopOff: "不循环", loopOffTip: "播完就换下一首",
      loopOne: "单曲循环", loopOneTip: "一直重复当前这首", loopQueue: "列表循环", loopQueueTip: "播完的歌排到列表最后",
      playersAria: "播放器", nowPlaying: "正在播放", dropHint: "把待播卡片拖到这里，立即播放",
      biliAccount: "Bilibili 账号", queueTitle: "待播列表", shuffle: "随机打乱顺序", clearList: "清空待播列表",
      clearAgain: "再按一次清空", emptyTitle: "列表是空的", emptySub: "在下方粘贴链接，或在 Discord 使用 /play",
      queueMore: "只画出前 {shown} 首，后面还有 {more} 首（按顺序会播到）",
      queueScroll: "已加载 {shown}／{total} 首，往下滚动加载更多",
      queueAria: "待播卡片，可拖动调整顺序", addAria: "歌曲链接或关键词",
      addPh: "粘贴 Bilibili／YouTube／Spotify 链接、BV 号，或输入关键词",
      nextTip: "插到最前面，这首播完就换它（Shift+Enter）", next: "下一首", addTip: "加到列表最后（Enter）", add: "添加",
      trashTitle: "删除区", trashHint: "拖到这里松开<br>即可删除", close: "关闭", biliQrAlt: "Bilibili 登录二维码",
      biliScan: "请用 Bilibili App 扫描", logout: "退出登录", scanLogin: "扫码登录",
      verifyTitle: "请从 Discord 的专属链接进入",
      verifyStep1: "在这个服务器的任意文字频道输入 <code>/help</code>",
      verifyStep2: "点击机器人回复里的“<b>点此打开看板</b>”",
      verifySub: "点一下就会自动确认你的 Discord 身份、显示你的昵称，并记住这个浏览器，之后直接打开这个网址就能进来。<br>链接只有你看得到，12 小时有效，请勿转发。",
      invalidTitle: "链接无效或已过期",
      invalidBody: "请回到 Discord，输入 <code>/help</code> 获取你专属的新链接。<br>链接 12 小时有效，且只能本人使用。",
      pickServer: "选择服务器", noGuild: "机器人还没有加入任何服务器。",
      detectBili: "识别为：Bilibili 链接", detectYt: "识别为：YouTube 链接", detectSpotify: "识别为：Spotify 链接（会去找对应的歌来播）",
      detectUrlHost: "识别为：网址（{host}）", detectUrl: "识别为：网址", detectBV: "识别为：Bilibili BV 号",
      detectAv: "识别为：Bilibili av 号", detectYtSearch: "识别为：YouTube 关键词搜索", detectBiliSearch: "识别为：Bilibili 关键词搜索",
      emptyChannelToast: "这个频道还没有开始播放：先在下面粘贴链接加一首歌，机器人就会进去",
      requestedBy: "点歌：{name}", requester: "点歌", playNow: "立即播放", remove: "删除",
      resume: "继续播放", pause: "暂停", nothingPlaying: "目前没有在播放",
      tabTitlePlaying: "播放中 · {title} · ", emptyTabStatus: "“{channel}”还没有开始播放 — 在下面粘贴链接，机器人就会进去",
      connectedTo: "已连接 · {channel}", notInVoice: "机器人还没有进入语音频道 — 请在 Discord 使用 /join 或 /play",
      loading: "加载中…", sourceChip: "来源 {quality} → Opus {bitrate} kbps", stopLeave: "停止并离开语音频道", seekAria: "播放进度",
      keyTip: "Enter 加到最后 · Shift+Enter 下一首 · 在页面任何地方 Ctrl+V 粘贴也行",
      resolvingEnd: "解析中，卡片稍后出现…", resolvingNext: "解析中，这首会插到最前面…", pasted: "已粘贴，解析中…",
      dropped: "已添加拖进来的链接，解析中…", yourChannel: "你所在的频道", addToChannel: "＋ 加到频道",
      freshTabTip: "“{name}”还没有开始播放：粘贴链接加一首歌，机器人就会进去，而且不会影响其他频道",
      notPlayingYet: "尚未播放", closeTab: "关闭这个标签页", closeTabNamed: "关闭“{name}”标签页",
      addToChannelTip: "选一个还没有播放器的语音频道，会开成一个独立的标签页（派一个空闲的机器人进去，不影响其他频道）",
      members: "{n} 人", nobody: "没人", playersUsed: "播放器 {used}／{total} 使用中", pickChannelFirst: "还没有在播放：先选一个语音频道",
      stutterCap: "检测到卡顿，同时播放上限已降为 {n} 个频道", idleClones: "还有 {n} 个空闲，可接手新的频道",
      allBusy: "全部使用中。要同时在更多频道播放，需要再配置分身（见 README）",
      inVoiceOnly: "人在语音频道里", readonly: "只读", joinFirst: "先加入语音频道，才能加歌",
      pasteTo: "粘贴链接，加到“{name}”（只会进这个频道）", thisChannel: "这个频道",
      biliLoggedOut: "未登录 Bilibili", biliSwap: "{vip}　点此更换账号", biliClickScan: "点此扫码登录",
      biliSwapBtn: "更换账号（扫码）", biliNote1: "<b>普通会员的音质上限与未登录相同</b>（约 192 kbps AAC）。Hi-Res 无损与杜比是<b>大会员</b>专属。",
      biliNote2: "<b>大会员</b>：机器人会优先使用 Hi-Res 无损（FLAC）音轨，搭配 Opus 320～510 kbps 最接近原音。",
      biliNote3: "登录后的主要好处：降低搜索被限流（HTTP 412）的概率、能播放需要登录才能看的视频。",
      biliNote4: "扫码是 Bilibili 官方的登录流程，机器人不会接触你的密码；登录凭证只保存在<b>运行机器人的这台电脑</b>，重启机器人仍会记住。",
      qrScanLeft: "请用 Bilibili App 扫描（{n} 秒后过期）", qrFetching: "正在向 Bilibili 获取二维码…",
      qrScanned: "已扫描，请在手机上点“确认登录”", qrExpired: "二维码已过期，请重新生成", qrRegen: "重新生成二维码",
      loginFailed: "登录失败", retry: "再试一次", loginOk: "登录成功：{name}",
      guest: "访客", guestN: "访客{n}", verified: "已确认身份：{name}，这个浏览器会被记住",
      revoked: "你的设备已被撤销，请重新用 /help 的链接进入", workerOffline: "播放端离线", reconnecting: "连接中断，正在重新连接…",
    },

    en: {
      title: "Music Dashboard", brand: "Music Dashboard", connecting: "Connecting…",
      quality: "Quality", qualityAria: "Quality (Opus bitrate)",
      q128: "Standard: 128 kbps (about 16 KB/s)", q192: "High: 192 kbps (default)", q256: "Very high: 256 kbps",
      q320: "Max: 320 kbps (about 40 KB/s)", q510: "Opus limit: 510 kbps (for lossless sources)",
      loopAria: "Loop mode", loopOff: "No loop", loopOffTip: "Play the next song when this one ends",
      loopOne: "Repeat one", loopOneTip: "Keep repeating the current song", loopQueue: "Repeat list", loopQueueTip: "Played songs go to the end of the list",
      playersAria: "Players", nowPlaying: "Now playing", dropHint: "Drag a queued card here to play it right away",
      biliAccount: "Bilibili account", queueTitle: "Queue", shuffle: "Shuffle", clearList: "Clear the queue",
      clearAgain: "Press again to clear", emptyTitle: "The queue is empty", emptySub: "Paste a link below, or use /play in Discord",
      queueMore: "Showing the first {shown}, {more} more follow in order",
      queueScroll: "Loaded {shown} of {total}, scroll down for more",
      queueAria: "Queued songs, drag to reorder", addAria: "Song link or keywords",
      addPh: "Paste a Bilibili / YouTube / Spotify link or a BV id, or type keywords",
      nextTip: "Insert at the front, plays right after this song (Shift+Enter)", next: "Play next", addTip: "Add to the end of the queue (Enter)", add: "Add",
      trashTitle: "Trash", trashHint: "Drop here<br>to delete", close: "Close", biliQrAlt: "Bilibili login QR code",
      biliScan: "Scan with the Bilibili app", logout: "Log out", scanLogin: "Log in with QR",
      verifyTitle: "Open the dashboard from your Discord link",
      verifyStep1: "Type <code>/help</code> in any text channel of this server",
      verifyStep2: "Click “<b>Open the dashboard</b>” in the bot's reply",
      verifySub: "One click confirms your Discord identity, shows your nickname and remembers this browser, so next time you can open this address directly.<br>Only you can see the link, it works for 12 hours, please don't share it.",
      invalidTitle: "This link is invalid or has expired",
      invalidBody: "Go back to Discord and type <code>/help</code> to get a new personal link.<br>A link works for 12 hours and only for you.",
      pickServer: "Pick a server", noGuild: "The bot is not in any server yet.",
      detectBili: "Detected: Bilibili link", detectYt: "Detected: YouTube link", detectSpotify: "Detected: Spotify link (a matching song is found and played)",
      detectUrlHost: "Detected: link ({host})", detectUrl: "Detected: link", detectBV: "Detected: Bilibili BV id",
      detectAv: "Detected: Bilibili av id", detectYtSearch: "Detected: YouTube keyword search", detectBiliSearch: "Detected: Bilibili keyword search",
      emptyChannelToast: "This channel isn't playing yet: add a song below first, the bot will join it",
      requestedBy: "Requested by {name}", requester: "Added by", playNow: "Play now", remove: "Remove",
      resume: "Resume", pause: "Pause", nothingPlaying: "Nothing is playing",
      tabTitlePlaying: "Playing · {title} · ", emptyTabStatus: "“{channel}” isn't playing yet — paste a link below, the bot will join it",
      connectedTo: "Connected · {channel}", notInVoice: "The bot is not in a voice channel — use /join or /play in Discord",
      loading: "Loading…", sourceChip: "Source {quality} → Opus {bitrate} kbps", stopLeave: "Stop and leave the voice channel", seekAria: "Playback position",
      keyTip: "Enter adds to the end · Shift+Enter plays next · Ctrl+V anywhere on the page also works",
      resolvingEnd: "Resolving, the card shows up soon…", resolvingNext: "Resolving, this song goes to the front…", pasted: "Pasted, resolving…",
      dropped: "Added the dropped link, resolving…", yourChannel: "Your channel", addToChannel: "+ Add channel",
      freshTabTip: "“{name}” isn't playing yet: paste a link to add a song, the bot will join, other channels are not affected",
      notPlayingYet: "Not playing", closeTab: "Close this tab", closeTabNamed: "Close the “{name}” tab",
      addToChannelTip: "Pick a voice channel that has no player yet. It opens as its own tab (an idle bot joins it, other channels are not affected)",
      members: "{n} people", nobody: "empty", playersUsed: "Players {used} / {total} in use", pickChannelFirst: "Nothing is playing yet: pick a voice channel first",
      stutterCap: "Stutter detected, the simultaneous limit is now {n} channels", idleClones: "{n} idle, ready for a new channel",
      allBusy: "All in use. To play in more channels at once, set up more clones (see README)",
      inVoiceOnly: "people in a voice channel", readonly: "Read only", joinFirst: "Join a voice channel first to add songs",
      pasteTo: "Paste a link to add it to “{name}” (only this channel)", thisChannel: "this channel",
      biliLoggedOut: "Not logged in to Bilibili", biliSwap: "{vip}  Click to switch account", biliClickScan: "Click to log in with QR",
      biliSwapBtn: "Switch account (QR)", biliNote1: "<b>A regular member gets the same quality cap as logged out</b> (about 192 kbps AAC). Hi-Res lossless and Dolby are for <b>premium members</b> only.",
      biliNote2: "<b>Premium member</b>: the bot prefers the Hi-Res lossless (FLAC) track, with Opus 320–510 kbps it is closest to the original.",
      biliNote3: "What logging in gives you: fewer search rate limits (HTTP 412), and videos that need a login can play.",
      biliNote4: "QR login is Bilibili's official flow, the bot never sees your password. The login stays only on <b>the computer running the bot</b> and is remembered after a restart.",
      qrScanLeft: "Scan with the Bilibili app (expires in {n} s)", qrFetching: "Getting a QR code from Bilibili…",
      qrScanned: "Scanned, tap “Confirm login” on your phone", qrExpired: "The QR code expired, generate a new one", qrRegen: "New QR code",
      loginFailed: "Login failed", retry: "Try again", loginOk: "Logged in: {name}",
      guest: "Guest", guestN: "Guest{n}", verified: "Identity confirmed: {name}, this browser will be remembered",
      revoked: "This device was revoked, open the link from /help again", workerOffline: "Player offline", reconnecting: "Connection lost, reconnecting…",
    },

    ja: {
      title: "ミュージックボード", brand: "ミュージックボード", connecting: "接続中…",
      quality: "音質", qualityAria: "音質（Opus ビットレート）",
      q128: "標準：128 kbps（約 16 KB/s）", q192: "高：192 kbps（既定）", q256: "最高に近い：256 kbps",
      q320: "最高：320 kbps（約 40 KB/s）", q510: "Opus の上限：510 kbps（ロスレス音源向け）",
      loopAria: "ループ", loopOff: "ループなし", loopOffTip: "再生が終わったら次の曲へ",
      loopOne: "1曲ループ", loopOneTip: "今の曲を繰り返す", loopQueue: "リストループ", loopQueueTip: "再生した曲をリストの最後に回す",
      playersAria: "プレイヤー", nowPlaying: "再生中", dropHint: "待機中のカードをここへドラッグすると、すぐに再生します",
      biliAccount: "Bilibili アカウント", queueTitle: "再生待ち", shuffle: "シャッフル", clearList: "再生待ちを空にする",
      clearAgain: "もう一度押して空にする", emptyTitle: "リストは空です", emptySub: "下にリンクを貼るか、Discord で /play を使ってください",
      queueMore: "先頭の {shown} 曲だけ表示しています。この後に {more} 曲が順番に続きます",
      queueScroll: "{total} 曲中 {shown} 曲を読み込み済み。下にスクロールすると続きを読み込みます",
      queueAria: "再生待ちのカード（ドラッグで並べ替え）", addAria: "曲のリンクまたはキーワード",
      addPh: "Bilibili／YouTube／Spotify のリンク、BV 番号、またはキーワードを入力",
      nextTip: "先頭に入れる（この曲の次に再生）（Shift+Enter）", next: "次に再生", addTip: "リストの最後に追加（Enter）", add: "追加",
      trashTitle: "削除エリア", trashHint: "ここで離すと<br>削除されます", close: "閉じる", biliQrAlt: "Bilibili ログイン用 QR コード",
      biliScan: "Bilibili アプリで読み取ってください", logout: "ログアウト", scanLogin: "QR でログイン",
      verifyTitle: "Discord の専用リンクから入ってください",
      verifyStep1: "このサーバーのテキストチャンネルで <code>/help</code> と入力",
      verifyStep2: "ボットの返信にある「<b>ボードを開く</b>」を押す",
      verifySub: "押すだけで Discord の本人確認とニックネーム表示が行われ、このブラウザーが記憶されます。次回からはこのアドレスを直接開けます。<br>リンクは本人にしか見えず、12 時間有効です。共有しないでください。",
      invalidTitle: "リンクが無効、または期限切れです",
      invalidBody: "Discord に戻って <code>/help</code> と入力し、新しい専用リンクを取得してください。<br>リンクは 12 時間有効で、本人だけが使えます。",
      pickServer: "サーバーを選択", noGuild: "ボットはまだどのサーバーにも参加していません。",
      detectBili: "認識：Bilibili のリンク", detectYt: "認識：YouTube のリンク", detectSpotify: "認識：Spotify のリンク（対応する曲を探して再生します）",
      detectUrlHost: "認識：リンク（{host}）", detectUrl: "認識：リンク", detectBV: "認識：Bilibili の BV 番号",
      detectAv: "認識：Bilibili の av 番号", detectYtSearch: "認識：YouTube のキーワード検索", detectBiliSearch: "認識：Bilibili のキーワード検索",
      emptyChannelToast: "このチャンネルはまだ再生していません。下で曲を追加すると、ボットが入ります",
      requestedBy: "リクエスト：{name}", requester: "リクエスト", playNow: "今すぐ再生", remove: "削除",
      resume: "再開", pause: "一時停止", nothingPlaying: "再生中の曲はありません",
      tabTitlePlaying: "再生中 · {title} · ", emptyTabStatus: "「{channel}」はまだ再生していません — 下にリンクを貼ると、ボットが入ります",
      connectedTo: "接続済み · {channel}", notInVoice: "ボットはボイスチャンネルにいません — Discord で /join か /play を使ってください",
      loading: "読み込み中…", sourceChip: "ソース {quality} → Opus {bitrate} kbps", stopLeave: "停止してボイスチャンネルから退出", seekAria: "再生位置",
      keyTip: "Enter で最後に追加 · Shift+Enter で次に再生 · ページのどこでも Ctrl+V で貼り付け可",
      resolvingEnd: "解析中です。カードはまもなく表示されます…", resolvingNext: "解析中です。この曲は先頭に入ります…", pasted: "貼り付けました。解析中…",
      dropped: "ドロップしたリンクを追加しました。解析中…", yourChannel: "あなたのチャンネル", addToChannel: "＋ チャンネルを追加",
      freshTabTip: "「{name}」はまだ再生していません。リンクを貼って曲を追加するとボットが入ります（他のチャンネルには影響しません）",
      notPlayingYet: "未再生", closeTab: "このタブを閉じる", closeTabNamed: "「{name}」のタブを閉じる",
      addToChannelTip: "プレイヤーのないボイスチャンネルを選ぶと、独立したタブとして開きます（空いているボットが入り、他のチャンネルには影響しません）",
      members: "{n} 人", nobody: "誰もいない", playersUsed: "プレイヤー {used}／{total} 使用中", pickChannelFirst: "まだ再生していません：先にボイスチャンネルを選んでください",
      stutterCap: "音切れを検出したため、同時再生の上限を {n} チャンネルに下げました", idleClones: "空きが {n} 個あり、新しいチャンネルを引き受けられます",
      allBusy: "すべて使用中です。さらに多くのチャンネルで同時に再生するには、分身ボットを追加してください（README 参照）",
      inVoiceOnly: "ボイスチャンネルにいる人", readonly: "閲覧のみ", joinFirst: "曲を追加するには、先にボイスチャンネルに入ってください",
      pasteTo: "リンクを貼って「{name}」に追加（このチャンネルだけ）", thisChannel: "このチャンネル",
      biliLoggedOut: "Bilibili 未ログイン", biliSwap: "{vip}　クリックでアカウント変更", biliClickScan: "クリックして QR でログイン",
      biliSwapBtn: "アカウント変更（QR）", biliNote1: "<b>一般会員の音質上限は未ログインと同じ</b>（約 192 kbps AAC）です。Hi-Res ロスレスとドルビーは<b>大会員</b>専用です。",
      biliNote2: "<b>大会員</b>：ボットは Hi-Res ロスレス（FLAC）を優先し、Opus 320〜510 kbps で原音に最も近づけます。",
      biliNote3: "ログインの主な利点：検索のレート制限（HTTP 412）が減り、ログインが必要な動画も再生できます。",
      biliNote4: "QR ログインは Bilibili 公式の方式で、ボットがパスワードに触れることはありません。認証情報は<b>ボットを動かしているこのパソコン</b>にだけ保存され、再起動後も保持されます。",
      qrScanLeft: "Bilibili アプリで読み取ってください（あと {n} 秒で期限切れ）", qrFetching: "Bilibili から QR コードを取得中…",
      qrScanned: "読み取りました。スマホで「ログインを確認」を押してください", qrExpired: "QR コードの期限が切れました。作り直してください", qrRegen: "QR コードを作り直す",
      loginFailed: "ログインに失敗しました", retry: "もう一度", loginOk: "ログインしました：{name}",
      guest: "ゲスト", guestN: "ゲスト{n}", verified: "本人確認が完了しました：{name}、このブラウザーを記憶します",
      revoked: "この端末は無効になりました。/help のリンクからもう一度入ってください", workerOffline: "プレイヤーがオフライン", reconnecting: "接続が切れました。再接続中…",
    },
  };

  let lang = "zh-TW";
  try {
    const saved = localStorage.getItem("mb_lang");
    if (saved && D[saved]) lang = saved;
  } catch { /* 瀏覽器禁止儲存時就用預設 / storage blocked: use the default */ }

  /** 取得翻譯，{x} 換成 vars.x；缺的 key 退回繁體中文，再缺就回傳 key 本身 / Get a translation; {x} becomes vars.x; a missing key falls back to Traditional Chinese, then to the key itself. */
  function T(key, vars) {
    let s = (D[lang] && D[lang][key]) ?? D["zh-TW"][key] ?? key;
    if (vars) s = s.replace(/\{(\w+)\}/g, (all, k) => (k in vars ? vars[k] : all));
    return s;
  }

  /** 把 data-i18n* 標記的節點換成目前語言 / Fill every data-i18n* node with the current language. */
  function apply(root = document) {
    document.documentElement.lang = HTML_LANG[lang];
    document.title = T("title");
    for (const [attr, set] of [
      ["data-i18n", (n, v) => { n.textContent = v; }],
      ["data-i18n-html", (n, v) => { n.innerHTML = v; }],
      ["data-i18n-title", (n, v) => { n.title = v; }],
      ["data-i18n-aria", (n, v) => { n.setAttribute("aria-label", v); }],
      ["data-i18n-ph", (n, v) => { n.placeholder = v; }],
      ["data-i18n-alt", (n, v) => { n.alt = v; }],
    ]) {
      root.querySelectorAll(`[${attr}]`).forEach((n) => set(n, T(n.getAttribute(attr))));
    }
  }

  /** 換語言：存起來再重新整理，最簡單也不會有畫面殘留舊語言 / Switch language: save it and reload, which is the simplest way to leave nothing in the old language on screen. */
  function setLang(next) {
    if (!D[next] || next === lang) return;
    try { localStorage.setItem("mb_lang", next); } catch { /* 沒有儲存空間就只在這次有效 / no storage: it only lasts until the reload */ }
    location.reload();
  }

  window.I18N = { T, apply, setLang, LANGS, get lang() { return lang; } };
  window.T = T;

  document.addEventListener("DOMContentLoaded", () => {
    apply();
    const sel = document.getElementById("langSelect");
    if (sel) {
      for (const [code, name] of LANGS) sel.add(new Option(name, code));
      sel.value = lang;
      sel.addEventListener("change", () => setLang(sel.value));
    }
  });
})();
