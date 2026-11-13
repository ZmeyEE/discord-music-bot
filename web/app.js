/* ==========================================================================
   音樂看板 — 前端邏輯（原生 JS，無建置步驟）
   Music dashboard — front-end logic (vanilla JS, no build step)

   - 與機器人用 WebSocket 即時同步：伺服器每次狀態改變都會推送完整快照
     Stays in sync with the bot over a WebSocket: every state change pushes a full snapshot.
   - 渲染採"以 id 為 key 的差異更新"：只動有變的卡片，其餘 DOM（含已解碼的圖片）原封不動
     Rendering is a keyed diff (by track id): only changed cards are touched, the rest of the DOM
     (including already-decoded images) is left alone.
   - 拖曳使用 SortableJS（web/vendor/Sortable.min.js，MIT）
     Drag & drop uses SortableJS (web/vendor/Sortable.min.js, MIT licence).
   - 網址加上 ?perf 可在主控台看到每次渲染的耗時
     Add ?perf to the URL to see each render's duration in the console.

   檔案地圖 / File map (search for the banners below):
     小工具 Helpers -> 沒指定伺服器 Server picker -> 狀態 State -> 撕裂特效 Tear effect -> 卡片 Cards
     -> 渲染 Rendering -> 驗證畫面 Verify gate -> 進度條 Seek bar -> 拖曳 Drag & drop -> 其他控制項 Controls
     -> 加歌 Adding songs -> 分頁 Player tabs -> 權限 Permissions -> Bilibili 帳號 Bilibili account -> 連線 Connection
   ========================================================================== */
(() => {
  "use strict";

  const $ = (s) => document.querySelector(s);                       // 查詢單一節點的簡寫 / shorthand for querySelector
  const NS = "http://www.w3.org/2000/svg";                           // SVG 命名空間 / SVG namespace
  const REDUCED_MOTION = matchMedia("(prefers-reduced-motion: reduce)").matches;   // 使用者是否要求減少動態效果 / does the user ask for reduced motion?
  const PERF = new URLSearchParams(location.search).has("perf");     // 是否開啟效能紀錄 / performance logging switch
  const m = location.pathname.match(/^\/g\/(\d+)/);                  // 網址 /g/<伺服器 id> / URL pattern /g/<guild id>

  /* ---------------------------------------------------------- 小工具 / Helpers */

  /** 建立元素並設定 class 與文字 / Create an element with an optional class and text. */
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  };

  /** 建立引用 index.html 圖示庫的 <svg> / Build an <svg> that references the icon sprite in index.html. */
  const icon = (name, cls = "i") => {
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("class", cls);
    svg.setAttribute("aria-hidden", "true");
    const use = document.createElementNS(NS, "use");
    use.setAttribute("href", `#i-${name}`);
    svg.appendChild(use);
    return svg;
  };

  /** 秒數 → m:ss 或 h:mm:ss / Seconds -> m:ss or h:mm:ss. */
  const fmt = (sec) => {
    if (sec == null || Number.isNaN(sec)) return "--:--";
    sec = Math.max(0, Math.floor(sec));
    const h = Math.floor(sec / 3600), mi = Math.floor((sec % 3600) / 60), s = sec % 60;
    return (h ? `${h}:${String(mi).padStart(2, "0")}` : `${mi}`) + `:${String(sec % 60).padStart(2, "0")}`;
  };

  /** 只在內容真的改變時才寫入，避免無謂的 DOM 變動與重繪 / Write only when the text really changed, avoiding needless DOM churn and repaints. */
  const setText = (node, text) => { if (node.textContent !== text) node.textContent = text; };

  /**
   * Bilibili 圖床的縮圖原圖約 250KB（1920 級），但卡片只顯示 ~130px
   * 官方圖床支援尺寸參數，縮成 webp 後只剩 3~7KB，解碼成本差一個數量級
   *
   * Bilibili's CDN thumbnails are ~250 KB (1920 px class) while a card shows only ~130 px.
   * The CDN supports size parameters; as webp the image shrinks to 3-7 KB, an order of magnitude
   * cheaper to decode.
   */
  function sized(url, w) {
    if (!url || url.includes("@")) return url;
    try {
      if (/(^|\.)hdslb\.com$/.test(new URL(url).hostname)) return `${url}@${w}w_${Math.round((w * 9) / 16)}h_1c.webp`;
    } catch { /* 不是合法網址就原樣回傳 / not a valid URL: return it unchanged */ }
    return url;
  }

  let toastTimer;
  /** 顯示一則短暫的提示訊息（約 4.8 秒）/ Show a short toast message (about 4.8 s). */
  function toast(text) {
    const t = $("#toast");
    t.textContent = text;
    t.hidden = false;
    t.style.animation = "none"; void t.offsetWidth; t.style.animation = "";   // 重新觸發 CSS 動畫 / restart the CSS animation
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (t.hidden = true), 4800);
  }

  /** 更新頂部的連線狀態文字與顏色（ok=綠／bad=紅）/ Update the connection status text and colour (ok = green, bad = red). */
  function setStatus(text, ok) {
    const s = $("#status");
    setText(s, text);
    const cls = "status " + (ok ? "ok" : "bad");
    if (s.className !== cls) s.className = cls;
  }

  /** 依網址判斷來源，用在卡片上的小標籤 / Work out the source site from a URL, for the small label on cards. */
  function sourceOf(url) {
    try {
      const h = new URL(url).hostname;
      if (/(^|\.)(bilibili\.com|b23\.tv)$/.test(h)) return { cls: "src-bili", label: "Bilibili" };
      if (/(^|\.)(youtube\.com|youtu\.be)$/.test(h)) return { cls: "src-yt", label: "YouTube" };
      return { cls: "", label: h.replace(/^www\./, "") };
    } catch { return null; }
  }

  /**
   * 與伺服器端 normalize_query 相同的規則，只用來即時顯示"辨識為…"
   * Mirrors the server's normalize_query; used only to show the live "Detected as ..." hint.
   */
  function detect(raw) {
    const q = raw.trim();
    if (!q) return null;
    const u = q.match(/https?:\/\/[^\s<>"'「」『』【】（）]+/i);
    if (u) {
      try {
        const h = new URL(u[0]).hostname;
        if (/(^|\.)(bilibili\.com|b23\.tv)$/.test(h)) return { k: "bili", t: "辨識為：Bilibili 連結" };
        if (/(^|\.)(youtube\.com|youtu\.be)$/.test(h)) return { k: "yt", t: "辨識為：YouTube 連結" };
        return { k: "", t: `辨識為：網址（${h.replace(/^www\./, "")}）` };
      } catch { return { k: "", t: "辨識為：網址" }; }
    }
    if (/(^|[^0-9A-Za-z])BV[0-9A-Za-z]{10}($|[^0-9A-Za-z])/.test(q)) return { k: "bili", t: "辨識為：Bilibili BV 號" };
    if (/(^|[^0-9A-Za-z])av\d{4,}($|[^0-9A-Za-z])/i.test(q)) return { k: "bili", t: "辨識為：Bilibili av 號" };
    if (/^(yt|youtube)\s*[:：]/i.test(q)) return { k: "yt", t: "辨識為：YouTube 關鍵字搜尋" };
    return { k: "bili", t: "辨識為：Bilibili 關鍵字搜尋" };
  }

  /* ------------------------------------------- 沒指定伺服器：顯示選單 / No server in the URL: show a picker */
  if (!m) {
    $("#board").hidden = true;
    document.querySelector(".topbar").hidden = true;
    $("#picker").hidden = false;
    fetch("/api/guilds").then((r) => r.json()).then((list) => {
      if (list.length === 1) { location.replace(`/g/${list[0].id}`); return; }   // 只有一個伺服器就直接進去 / only one server: go straight in
      const box = $("#pickerList");
      if (!list.length) box.textContent = "機器人還沒加入任何伺服器。";
      list.forEach((g) => {
        const a = el("a", "", g.name);
        a.href = `/g/${g.id}`;
        box.appendChild(a);
      });
    });
    return;
  }

  /* ----------------------------------------------------------- 狀態 / State */
  const gid = m[1];   // 目前看的伺服器 id / the guild (server) id being viewed

  // 存取憑證：/help 給的連結帶 ?t=…；記在這台瀏覽器（重新整理仍有效），並從網址列拿掉，避免被截圖或轉貼時外流
  // Access token: the /help link carries ?t=...; it is kept in this browser (survives reloads) and removed
  // from the address bar so it doesn't leak through screenshots or copy-paste.
  const TOKEN_KEY = `mb_token_${gid}`;
  const urlToken = new URLSearchParams(location.search).get("t");
  try {
    if (urlToken) {
      localStorage.setItem(TOKEN_KEY, urlToken);
      history.replaceState(null, "", location.pathname);
    }
  } catch { /* 瀏覽器禁止儲存時，只在這次有效 / storage blocked: the token only works for this visit */ }
  let token = urlToken || (() => { try { return localStorage.getItem(TOKEN_KEY); } catch { return null; } })();

  // 裝置憑證：在 Discord 驗證過後，主機發給這個瀏覽器的長憑證（主機只存它的雜湊），之後開看板就不用再驗證
  // Device token: the long token the host hands to this browser after Discord verification (the host stores
  // only its hash). With it you don't need to verify again next time.
  const DEVICE_KEY = `mb_device_${gid}`;
  let device = null;
  try { device = localStorage.getItem(DEVICE_KEY); } catch { /* 沒有儲存空間就每次重新驗證 / no storage: verify every time */ }
  const saveDevice = (t) => { device = t; try { t ? localStorage.setItem(DEVICE_KEY, t) : localStorage.removeItem(DEVICE_KEY); } catch { /* 忽略 / ignore */ } };

  let state = null;      // 最新的伺服器快照 / the latest server snapshot
  // "＋ 加到頻道"開出來的分頁：頻道還沒有播放器時，先在畫面上是一個獨立的空分頁
  // targetChannel = 目前正在看的那個空分頁（頻道 id）；pendingTabs = 已開但還沒有開始播放的分頁
  // Tabs opened with "+ add to channel": while a channel has no player yet it is an independent empty tab on screen.
  // targetChannel = the empty tab currently being viewed (channel id); pendingTabs = tabs opened but not playing yet.
  let targetChannel = null;
  let pendingTabs = [];
  let ws = null, retry = 0;
  let dragging = false;  // 拖曳卡片中不重畫，避免卡片從手上消失 / no re-render while dragging a card, so it doesn't vanish from the hand
  let seeking = false;   // 拖曳進度條中也不重畫（否則進度條會在手上被換掉）/ no re-render while dragging the seek bar either (it would be replaced under the finger)
  let deferred = null;   // 拖曳中收到的最新快照，放開後再套用 / the newest snapshot received mid-drag, applied afterwards
  let recvAt = 0;        // 收到快照的時間，用來在本地推算播放進度 / when the snapshot arrived, used to extrapolate the playback position
  const handled = new Set();   // 這次拖曳已處理過的卡片（避免重複刪除）/ cards already handled in this drag (prevents double deletion)

  // 常用節點只查一次 / look the frequently used nodes up only once
  const queueEl = $("#queue"), nowDrop = $("#nowDrop"), trashCol = $("#trashCol");
  const queuePanel = document.querySelector(".col-queue");
  const guildNameEl = $("#guildName"), countEl = $("#queueCount");
  const loopBtns = [...document.querySelectorAll("#loopBtns button")];
  const qualityBtns = [...document.querySelectorAll("#qualityBtns button")];

  // 空分頁（頻道還沒有播放器）只能"加歌"：其他操作會落在另一個頻道的播放器上，所以直接擋下，絕不影響其他頻道
  // An empty tab (the channel has no player yet) may only "add a song": other actions would land on another
  // channel's player, so they are blocked here and can never affect other channels.
  const OK_ON_EMPTY_TAB = new Set(["add", "select", "quality", "bili_login_start", "bili_login_cancel", "bili_logout"]);

  /** 送一則訊息給伺服器（連線中才送；空分頁會擋下不允許的操作）/ Send a message to the server (only while connected; empty tabs block disallowed actions). */
  const send = (obj) => {
    if (targetChannel && !OK_ON_EMPTY_TAB.has(obj.type)) { toast("這個頻道還沒有開始播放：先在下面貼上網址加一首歌，機器人就會進去"); return; }
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
  };

  /* ----------------------------------------------------- 撕裂消失特效 / Tear-away effect */
  /**
   * 把元素複製成左右兩片，沿著鋸齒狀的撕裂線裁開，
   * 兩片各自旋轉、飄開並淡出，最後移除，只用 transform / opacity，全程在合成階段處理
   *
   * Clone the element into a left and a right piece, cut along a jagged tear line; each piece rotates,
   * drifts away, fades and is finally removed. Only transform / opacity are animated, so it all runs
   * on the compositor.
   *
   * @param {Element} node            要撕掉的元素 / the element to tear
   * @param {number} delay            動畫延遲（毫秒）/ animation delay in ms
   * @param {DOMRect|null} rectOverride 指定位置（拖曳中元素已不在原處時用）/ explicit rectangle (used when the node is no longer where it was)
   */
  function tearAway(node, delay = 0, rectOverride = null) {
    if (!node || (!rectOverride && !node.isConnected)) return;
    // 這是一次性的短暫回饋，所以即使系統設為"減少動態效果"也會播放，只是幅度與時間減半
    // This is brief one-off feedback, so it plays even with "reduce motion" on, just at half the distance and duration.
    const k = REDUCED_MOTION ? 0.5 : 1;
    const r = rectOverride || node.getBoundingClientRect();
    if (r.width < 8 || r.height < 8) return;

    // 鋸齒撕裂線：從上到下，x 在中間附近隨機抖動
    // Jagged tear line: top to bottom, with x jittering randomly around the middle.
    const cx = 38 + Math.random() * 24;
    const steps = 14;
    const edge = [];
    for (let i = 0; i <= steps; i++) {
      const jag = (i % 2 ? 3.2 : -3.2) + (Math.random() - .5) * 4;
      edge.push([Math.min(92, Math.max(8, cx + jag)), (i / steps) * 100]);
    }
    const poly = (pts) => "polygon(" + pts.map(([x, y]) => `${x.toFixed(1)}% ${y.toFixed(1)}%`).join(", ") + ")";
    const pieces = [
      { clip: poly([[0, 0], ...edge, [0, 100]]), origin: "0% 100%", to: { x: -34 * k, y: 14 * k, rot: -9 * k } },
      { clip: poly([[100, 0], ...edge, [100, 100]]), origin: "100% 100%", to: { x: 34 * k, y: 6 * k, rot: 8 * k } },
    ];
    for (const p of pieces) {
      const wrap = el("div", "tear-piece");
      Object.assign(wrap.style, {
        left: `${r.left}px`, top: `${r.top}px`, width: `${r.width}px`, height: `${r.height}px`, transformOrigin: p.origin,
      });
      const clone = node.cloneNode(true);
      clone.classList.remove("sortable-fallback", "ghost");
      clone.removeAttribute("style");   // 拖曳中的浮動複本帶有 position:fixed 等行內樣式，要清掉 / the floating drag copy carries inline styles such as position:fixed; strip them
      clone.style.clipPath = p.clip;
      clone.style.webkitClipPath = p.clip;
      wrap.appendChild(clone);
      document.body.appendChild(wrap);
      wrap.animate(
        [
          { transform: "translate(0,0) rotate(0deg)", opacity: 1 },
          { transform: `translate(${p.to.x * .35}px, ${p.to.y * .2}px) rotate(${p.to.rot * .4}deg)`, opacity: .95, offset: .3 },
          { transform: `translate(${p.to.x}px, ${p.to.y + 26 * k}px) rotate(${p.to.rot}deg)`, opacity: 0 },
        ],
        { duration: 760 * (REDUCED_MOTION ? 0.75 : 1), delay, easing: "cubic-bezier(.25,.7,.3,1)", fill: "both" },
      ).onfinish = () => wrap.remove();
    }
  }

  /* ------------------------------------------------------------- 卡片 / Cards */

  /** 縮圖方塊：載入失敗或沒有網址時顯示音符圖示 / A thumbnail box; shows a note icon when there is no URL or loading fails. */
  function thumb(url, cls, width) {
    const box = el("div", cls);
    const fallback = () => box.appendChild(icon("note"));
    if (url) {
      const img = new Image();
      img.referrerPolicy = "no-referrer";
      img.decoding = "async";        // 解碼不佔用主執行緒 / decode off the main thread
      img.loading = "lazy";
      img.draggable = false;
      img.alt = "";
      img.onerror = () => { img.remove(); fallback(); };
      img.src = sized(url, width);
      box.appendChild(img);
    } else {
      fallback();
    }
    return box;
  }

  /** 圖示按鈕（附無障礙標籤，點擊不會冒泡）/ An icon button with accessibility labels; the click does not bubble up. */
  function actionButton(label, iconName, cls, onClick) {
    const b = el("button", cls);
    b.type = "button";
    b.title = label;
    b.setAttribute("aria-label", label);
    b.appendChild(icon(iconName));
    b.addEventListener("click", (e) => { e.stopPropagation(); onClick(); });
    return b;
  }

  /** 卡片的"內容簽章"：簽章沒變就不需要重建這張卡片 / A card's "content signature": an unchanged signature means the card needn't be rebuilt. */
  const cardSig = (t) => [t.title, t.thumbnail, t.duration, t.uploader, t.requester, t.requester_avatar].join("\u0001");

  /**
   * "點歌 [頭像] 暱稱"，沒有頭像（訪客、本地）或頭像載入失敗時，用暱稱的第一個字當圓形頭像
   * "Requested by [avatar] name". With no avatar (guest, local) or when it fails to load, the first
   * letter of the name is used as a round avatar.
   */
  function requesterNode(name, url) {
    const r = el("span", "req");
    r.title = `點歌：${name}`;
    const initial = () => el("span", "req-av req-initial", [...name][0] || "?");
    let av;
    if (url) {
      av = new Image();
      av.className = "req-av"; av.alt = ""; av.width = av.height = 18;
      av.referrerPolicy = "no-referrer"; av.decoding = "async"; av.loading = "lazy";
      av.addEventListener("error", () => av.replaceWith(initial()), { once: true });
      av.src = url;
    } else av = initial();
    r.append(el("span", "req-label", "點歌"), av, el("span", "req-name", name));
    return r;
  }

  /** 在 meta 列加上"上傳者"與"點歌者"/ Add the uploader and the requester to a card's meta row. */
  function fillWho(meta, t) {
    if (t.uploader) meta.appendChild(el("span", "who", t.uploader));
    if (t.requester) meta.appendChild(requesterNode(t.requester, t.requester_avatar));
  }

  /** 建立待播清單裡的一張卡片 / Build one card of the queue list. */
  function makeCard(t, index) {
    const c = el("div", "card");
    c.dataset.id = t.id;
    c.dataset.sig = cardSig(t);

    const th = thumb(t.thumbnail, "thumb", 320);
    const idx = el("span", "idx", String(index + 1));
    th.appendChild(idx);
    c._idx = idx;
    c.appendChild(th);

    const info = el("div", "info");
    info.appendChild(el("div", "title", t.title));
    const meta = el("div", "meta");
    if (t.duration) meta.appendChild(el("span", "pill", fmt(t.duration)));
    const src = sourceOf(t.url);
    if (src) meta.appendChild(el("span", `pill ${src.cls}`, src.label));
    fillWho(meta, t);
    info.appendChild(meta);
    c.appendChild(info);

    const act = el("div", "actions");
    act.append(
      actionButton("立即播放", "play", "", () => send({ type: "play_now", id: t.id })),
      actionButton("刪除", "close", "x", () => { tearAway(c); send({ type: "remove", id: t.id }); }),
    );
    c.appendChild(act);
    return c;
  }

  /* ------------------------------------------------------------- 渲染 / Rendering */
  const cardCache = new Map();   // id -> 卡片元素 / id -> card element

  /**
   * 待播清單的差異更新：只新增／移除／更新有變的卡片，順序不對才移動
   * Keyed diff of the queue list: add / remove / update only the cards that changed, and move a card
   * only when its position is wrong.
   */
  function syncQueue(list) {
    const wanted = new Set(list.map((t) => t.id));
    for (const [id, node] of cardCache) {
      if (!wanted.has(id)) { node.remove(); cardCache.delete(id); }
    }
    let cursor = queueEl.firstElementChild;
    list.forEach((t, i) => {
      let node = cardCache.get(t.id);
      if (!node) {
        node = makeCard(t, i);
        cardCache.set(t.id, node);
      } else if (node.dataset.sig !== cardSig(t)) {          // 內容變了（例如補抓到標題／縮圖）才重建 / rebuild only when content changed (e.g. title/thumbnail arrived)
        const fresh = makeCard(t, i);
        node.replaceWith(fresh);
        if (node === cursor) cursor = fresh;
        node = fresh;
        cardCache.set(t.id, node);
      }
      if (node._idx) setText(node._idx, String(i + 1));
      if (node === cursor) cursor = cursor.nextElementSibling;
      else queueEl.insertBefore(node, cursor);
    });
  }

  let nowKey = null;            // "正在播放"卡片的內容簽章 / content signature of the "now playing" card
  let nowRefs = null;           // 卡片內要頻繁更新的節點 / nodes inside the card that are updated often

  /** 依暫停狀態切換"暫停／繼續"按鈕的圖示 / Switch the pause/resume button's icon according to the paused state. */
  function setPauseButton(btn, paused) {
    const name = paused ? "play" : "pause";
    if (btn.dataset.icon === name) return;
    btn.dataset.icon = name;
    btn.replaceChildren(icon(name));
    btn.title = paused ? "繼續播放" : "暫停";
    btn.setAttribute("aria-label", btn.title);
  }

  /** 更新"正在播放"區塊（沒有歌時顯示空狀態）/ Update the "now playing" block (shows an idle state when nothing plays). */
  function syncNow(s) {
    const c = s.current;
    if (!c) {
      if (nowKey !== "idle") {
        const idle = el("div", "idle");
        idle.append(icon("note"), el("span", "", "目前沒有在播放"));
        nowDrop.replaceChildren(idle);
        nowKey = "idle"; nowRefs = null;
      }
      return;
    }
    const key = [c.id, c.title, c.thumbnail, c.duration, c.uploader, c.requester, c.requester_avatar, c.loading, c.quality, c.bitrate].join("\u0001");
    const present = nowDrop.firstElementChild && nowDrop.firstElementChild.dataset.current === "1";   // 卡片還在畫面上嗎 / is the card still on screen?
    if (key !== nowKey || !present) {          // 換歌、載入完成補上音質、或卡片被拖走後沒換歌：才重建整張卡片 / rebuild only on a song change, when loading finished and quality arrived, or when the card was dragged away without a song change
      nowDrop.replaceChildren(makeNowCard(s));
      nowKey = key;
    }
    if (nowRefs) setPauseButton(nowRefs.pause, s.paused);   // 暫停／繼續只換按鈕圖示 / pause/resume only swaps the button icon
  }

  /* ------------------------------------------------ 請用專屬連結進來（驗證模式）/ Please use your personal link (verify mode) ---- */
  const verifyGate = $("#verifyGate");
  let verifyOn = false;

  /** 顯示"請用專屬連結進來"畫面，隱藏看板 / Show the "use your personal link" screen and hide the dashboard. */
  function showVerify() {
    verifyOn = true;
    $("#board").hidden = true; document.querySelector(".topbar").hidden = true;
    playersBar.hidden = true; permBanner.hidden = true; limitBanner.hidden = true;
    verifyGate.hidden = false;
  }
  /** 驗證通過後恢復看板 / Restore the dashboard once verified. */
  function hideVerify() {
    verifyOn = false;
    verifyGate.hidden = true;
    $("#board").hidden = false; document.querySelector(".topbar").hidden = false;
  }

  /**
   * 正在看空分頁時，畫面上是"那個頻道自己的空狀態"，不是別的頻道的內容
   * When an empty tab is being viewed, the screen shows "that channel's own empty state", never another channel's content.
   */
  function viewOf(s) {
    if (!targetChannel) return s;
    const ch = s.channels.find((c) => c.id === targetChannel);
    return { ...s, current: null, queue: [], paused: false, loop: "off", connected: false, channel: ch ? ch.name : "", emptyTab: true };
  }
  /** 切換分頁後立刻重畫（不等伺服器回應，也不重置進度基準）/ Re-render at once after switching tabs (no server round-trip, and the progress baseline isn't reset). */
  function refresh() { if (state) render(state, true); }

  /**
   * 把伺服器快照畫到畫面上（所有畫面更新的入口）
   * Draw a server snapshot on screen (the single entry point for every screen update).
   * @param {object} s      伺服器快照 / the server snapshot
   * @param {boolean} again 是 refresh() 觸發的重畫（不更新 recvAt）/ true when triggered by refresh() (recvAt is not updated)
   */
  function render(s, again = false) {
    state = s;
    if (!again) recvAt = performance.now();
    if (s.me && s.me.pending) { showVerify(); return; }   // 還沒驗證：只顯示驗證畫面 / not verified yet: show only the verify screen
    if (verifyOn) hideVerify();
    if (dragging || seeking) { deferred = s; return; }   // 拖曳中先不畫，放開後再套用 / don't draw during a drag; apply after release
    const t0 = PERF ? performance.now() : 0;
    document.body.classList.remove("offline");            // 收到狀態 = 播放端在線（syncPerms 會依權限決定提示列要不要顯示）/ receiving state = the worker is online (syncPerms decides whether the banner shows)

    syncPlayers(s);                      // 先整理分頁（頻道開始播放後，空分頁會變成正式分頁），再依目前分頁畫內容 / tabs first (an empty tab becomes a real one once its channel starts playing), then draw the current tab
    const v = viewOf(s);
    document.body.classList.toggle("empty-tab", !!v.emptyTab);

    setText(guildNameEl, s.guild.name);
    const cur = v.current;
    const title = (cur ? `播放中 · ${cur.title} · ` : "") + "音樂看板";
    if (document.title !== title) document.title = title;
    setStatus(
      v.emptyTab
        ? `「${v.channel}」還沒有開始播放 — 在下面貼上網址，機器人就會進去`
        : v.connected
          ? `已連線 · ${v.channel}` + (cur && cur.bitrate ? ` · Opus ${cur.bitrate} kbps` : "")
          : "機器人尚未進入語音頻道 — 請在 Discord 使用 /join 或 /play",
      v.connected,
    );
    for (const b of loopBtns) b.setAttribute("aria-checked", String(b.dataset.loop === v.loop));
    for (const b of qualityBtns) b.setAttribute("aria-checked", String(Number(b.dataset.q) === s.quality.kbps));

    syncQueue(v.queue);
    setText(countEl, String(v.queue.length));
    queuePanel.classList.toggle("is-empty", v.queue.length === 0);
    syncNow(v);
    syncPerms(s);
    syncLimit(s);
    syncBili(s);
    tick();

    if (PERF) {
      const ms = performance.now() - t0;
      (window.__renderMs = window.__renderMs || []).push(+ms.toFixed(2));
      console.log(`[perf] render ${ms.toFixed(2)}ms（待播 ${s.queue.length} 首）`);
    }
  }

  /** 建立"正在播放"大卡片（封面、標題、進度條、控制按鈕）/ Build the big "now playing" card (art, title, seek bar, controls). */
  function makeNowCard(s) {
    const c = s.current;
    const card = el("div", "now-card");
    card.dataset.current = "1";
    card.appendChild(thumb(c.thumbnail, "art", 640));
    card.appendChild(el("div", "title", c.title));

    const meta = el("div", "meta");
    const src = sourceOf(c.url);
    if (src) meta.appendChild(el("span", `pill ${src.cls}`, src.label));
    fillWho(meta, c);
    card.appendChild(meta);

    if (c.loading) card.appendChild(el("span", "chip loading", "載入中…"));
    else if (c.quality) card.appendChild(el("span", "chip", `來源 ${c.quality} → Opus ${c.bitrate} kbps`));

    const seek = makeSeekBar(c);
    card.appendChild(seek);

    const times = el("div", "times");
    const pos = el("span", "", "0:00");
    times.append(pos, el("span", "", c.duration ? fmt(c.duration) : "--:--"));
    card.appendChild(times);

    const ctrl = el("div", "ctrl");
    const pause = actionButton("暫停", "pause", "main", () => send({ type: "toggle_pause" }));
    pause.dataset.icon = "pause";
    ctrl.append(
      actionButton("下一首", "next", "", () => send({ type: "skip" })),
      pause,
      actionButton("停止並離開語音頻道", "stop", "danger", () => send({ type: "stop" })),
    );
    card.appendChild(ctrl);

    nowRefs = { seek, pos, pause, duration: c.duration };
    return card;
  }

  /* ------------------------------------------------------------ 進度條 / Seek bar */
  /**
   * 可拖曳的進度條：點一下跳到該處，按住拖曳可預覽時間，放開才送出跳轉；也支援鍵盤左右鍵 ±5 秒
   * 沒有長度的曲目（直播）會停用，進度以 CSS 變數 --p（0~1）驅動
   *
   * A draggable seek bar: click to jump, press and drag to preview the time, the jump is sent on release;
   * the keyboard's Left/Right keys move it by +-5 s. Tracks without a duration (live streams) disable it.
   * The progress is driven by the CSS variable --p (0..1).
   */
  function makeSeekBar(c) {
    const seek = el("div", "seek");
    seek.setAttribute("role", "slider");
    seek.setAttribute("aria-label", "播放進度");
    seek.tabIndex = 0;
    const track = el("div", "seek-track");
    track.appendChild(el("div", "seek-fill"));
    const knob = el("div", "seek-knob");
    const tip = el("div", "seek-tip");
    seek.append(track, knob, tip);

    const dur = c.duration;
    if (!dur) { seek.classList.add("disabled"); return seek; }
    seek.setAttribute("aria-valuemin", "0");
    seek.setAttribute("aria-valuemax", String(dur));

    /** 指標位置 → 0~1 的比例 / Pointer position -> a 0..1 ratio. */
    const ratioOf = (e) => {
      const r = seek.getBoundingClientRect();
      return Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    };
    const show = (ratio) => {            // 把進度、提示泡泡都移到 ratio 位置 / move both the progress and the tooltip to `ratio`
      seek.style.setProperty("--p", ratio);
      tip.style.left = `${ratio * 100}%`;
      tip.textContent = fmt(ratio * dur);
    };
    /** 真正送出跳轉（秒數會被限制在 0~長度-1）/ Actually send the seek (seconds clamped to 0..duration-1). */
    const commit = (seconds) => {
      seconds = Math.max(0, Math.min(dur - 1, Math.round(seconds)));
      send({ type: "seek", position: seconds });
      if (state && state.current) { state.current.position = seconds; recvAt = performance.now(); }   // 先在本地反映，不等伺服器 / reflect it locally first, without waiting for the server
    };

    seek.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      e.stopPropagation();               // 不要讓外層的卡片拖曳（SortableJS）接手 / keep the outer card drag (SortableJS) from taking over
      e.preventDefault();
      seeking = true;
      seek.classList.add("active");
      seek.setPointerCapture(e.pointerId);
      const ratio = ratioOf(e);
      show(ratio);
      if (nowRefs) setText(nowRefs.pos, fmt(ratio * dur));
    });
    seek.addEventListener("pointermove", (e) => {
      const ratio = ratioOf(e);
      if (seeking) { show(ratio); if (nowRefs) setText(nowRefs.pos, fmt(ratio * dur)); }
      else { tip.style.left = `${ratio * 100}%`; tip.textContent = fmt(ratio * dur); }   // 滑過時預覽目標時間 / preview the target time while hovering
    });
    seek.addEventListener("pointerup", (e) => {
      if (!seeking) return;
      seeking = false;
      seek.classList.remove("active");
      commit(ratioOf(e) * dur);
      if (deferred) { const s = deferred; deferred = null; render(s); }
    });
    seek.addEventListener("pointercancel", () => { seeking = false; seek.classList.remove("active"); });
    seek.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      e.preventDefault();
      const now = state && state.current ? state.current.position + (performance.now() - recvAt) / 1000 : 0;
      commit(now + (e.key === "ArrowRight" ? 5 : -5));
    });
    return seek;
  }

  /**
   * 進度：以伺服器給的位置為基準，在本地推算，分頁隱藏時不做事
   * Progress: extrapolated locally from the position the server sent. Does nothing while the tab is hidden.
   */
  function tick() {
    if (document.hidden || seeking || !state || !state.current || !nowRefs) return;
    const c = state.current;
    const running = !state.paused && !c.loading;
    const pos = c.position + (running ? (performance.now() - recvAt) / 1000 : 0);
    const ratio = c.duration ? Math.min(1, pos / c.duration) : 0;
    setText(nowRefs.pos, fmt(pos));
    nowRefs.seek.style.setProperty("--p", ratio.toFixed(4));
  }
  setInterval(tick, 500);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) tick(); });

  /* ------------------------------------------------------------ 拖曳 / Drag & drop */
  // SortableJS 的共用設定 / options shared by every Sortable instance
  const common = {
    animation: 150, ghostClass: "ghost", forceFallback: true, fallbackOnBody: true, fallbackTolerance: 3,
    delay: 80, delayOnTouchOnly: true,
    // 明確告訴 SortableJS 版面是直的：它就不必在每次移動時用 getComputedStyle 去猜方向（會強制重算樣式）
    // Tell SortableJS the layout is vertical, so it doesn't guess the direction with getComputedStyle on
    // every move (which forces a style recalculation).
    direction: "vertical",
  };

  // 撕裂特效需要知道"使用者放開手時卡片在哪"，SortableJS 在 onAdd 時已把浮動卡片移除，
  // 所以自己記錄指標位置：開始拖曳時記下抓取點與卡片大小，拖曳中只記指標座標（不讀版面、不用 rAF）
  // The tear effect needs to know where the card was when the user let go. SortableJS has already removed
  // the floating card by onAdd, so we track the pointer ourselves: remember the grab point and card size
  // when the drag starts, and only record pointer coordinates during the drag (no layout reads, no rAF).
  let downPt = null, lastPt = null, grab = null, dragSize = null, dragClone = null;
  document.addEventListener("pointerdown", (e) => { downPt = { x: e.clientX, y: e.clientY }; }, true);
  document.addEventListener("pointermove", (e) => { if (dragging) lastPt = { x: e.clientX, y: e.clientY }; }, { passive: true });
  /** 放開手時，浮動卡片大約所在的矩形 / The rectangle where the floating card roughly was at release. */
  const ghostRect = () => (lastPt && grab && dragSize
    ? { left: lastPt.x - grab.x, top: lastPt.y - grab.y, width: dragSize.w, height: dragSize.h }
    : null);

  /** 開始拖曳：暫停重畫、記下抓取點與卡片大小 / Drag started: pause re-rendering and remember the grab point and card size. */
  const startDrag = (evt) => {
    dragging = true;
    document.body.classList.add("dragging");
    const r = evt.item.getBoundingClientRect();
    dragSize = { w: r.width, h: r.height };
    grab = downPt ? { x: downPt.x - r.left, y: downPt.y - r.top } : { x: r.width / 2, y: r.height / 2 };
    lastPt = downPt;
    dragClone = evt.item.cloneNode(true);
  };
  /** 結束拖曳：清理狀態並套用拖曳期間累積的最新快照 / Drag ended: clean up and apply the newest snapshot gathered during the drag. */
  const endDrag = () => {
    dragging = false;
    dragClone = null; grab = null; dragSize = null; lastPt = null;
    document.body.classList.remove("dragging");
    trashCol.classList.remove("over");
    handled.clear();
    if (deferred) { const s = deferred; deferred = null; render(s); }
  };

  /** 放開時滑鼠／手指是否在刪除區上（備援：即使 SortableJS 沒觸發 onAdd 也能刪除）/ Was the mouse/finger over the trash column at release? (a fallback so deletion works even if SortableJS didn't fire onAdd) */
  function releasedOverTrash(evt) {
    const e = evt.originalEvent;
    if (!e) return false;
    const p = (e.changedTouches && e.changedTouches[0]) || e;
    if (p.clientX == null) return false;
    const r = trashCol.getBoundingClientRect();
    return p.clientX >= r.left && p.clientX <= r.right && p.clientY >= r.top && p.clientY <= r.bottom;
  }

  /** 刪除一張被拖到刪除區的卡片：播撕裂特效並通知伺服器 / Delete a card dropped on the trash: play the tear effect and tell the server. */
  function deleteItem(item) {
    const key = item.dataset.id || "current";
    if (handled.has(key)) return;
    handled.add(key);
    const rect = ghostRect();
    if (dragClone && rect) tearAway(dragClone, 0, rect);   // 在放開手的地方撕開 / tear it where the hand let go
    else tearAway(item);
    if (item.dataset.current === "1") send({ type: "remove_current" });
    else send({ type: "remove", id: item.dataset.id });
    item.remove();
  }

  // 待播清單：可排序，也可拖出去（刪除區／正在播放）
  // The queue: sortable, and cards can be dragged out of it (to the trash / to "now playing").
  const sortQueue = new Sortable(queueEl, {
    ...common,
    group: { name: "cards", pull: true, put: false },
    onStart: startDrag,
    onEnd: (evt) => {
      if (evt.to === evt.from && evt.oldIndex !== evt.newIndex) {
        send({ type: "move", id: evt.item.dataset.id, index: evt.newIndex });
      } else if (evt.to === evt.from && releasedOverTrash(evt)) {
        deleteItem(evt.item);
      }
      endDrag();
    },
  });

  // 刪除區（整個右側欄位）：放進去就刪
  // Trash zone (the whole right-hand column): dropping a card here deletes it.
  new Sortable($("#trash"), {
    ...common,
    group: { name: "cards", pull: false, put: true },
    onAdd: (evt) => deleteItem(evt.item),
  });
  trashCol.addEventListener("pointerenter", () => dragging && trashCol.classList.add("over"));
  trashCol.addEventListener("pointerleave", () => trashCol.classList.remove("over"));

  // 正在播放：放進來 = 立即播放；"正在播放"卡片本身也能拖去刪除區（= 跳過並移除）
  // Now playing: dropping a card here = play it now; the "now playing" card itself can also be dragged to the trash (= skip and remove).
  const sortNow = new Sortable(nowDrop, {
    ...common,
    draggable: ".now-card",
    filter: ".seek, .ctrl",        // 進度條與控制按鈕上按下去，不要變成拖曳卡片 / pressing on the seek bar or controls must not start a card drag
    preventOnFilter: false,
    sort: false,
    group: { name: "cards", pull: true, put: true },
    onStart: startDrag,
    onAdd: (evt) => {
      const id = evt.item.dataset.id;
      evt.item.remove();
      send({ type: "play_now", id });
    },
    onEnd: (evt) => {
      if (evt.to === evt.from && releasedOverTrash(evt)) deleteItem(evt.item);
      endDrag();
    },
  });

  /* ------------------------------------------------------ 其他控制項 / Other controls */
  loopBtns.forEach((b) => b.addEventListener("click", () => send({ type: "loop", mode: b.dataset.loop })));
  qualityBtns.forEach((b) => b.addEventListener("click", () => {
    if (state && state.quality.kbps === Number(b.dataset.q)) return;   // 已經是這個音質 / already this quality
    send({ type: "quality", kbps: Number(b.dataset.q) });
  }));

  $("#btnShuffle").addEventListener("click", () => send({ type: "shuffle" }));

  // 清空：第一次按先"上膛"，3 秒內再按一次才真的清空（取代瀏覽器內建的 confirm 對話框）
  // Clear: the first press only "arms" the button; a second press within 3 s really clears (replaces the
  // browser's built-in confirm dialog).
  const clearBtn = $("#btnClear");
  let armedTimer;
  clearBtn.addEventListener("click", () => {
    if (!state || !state.queue.length) return;
    if (!clearBtn.classList.contains("armed")) {
      clearBtn.classList.add("armed");
      armedTimer = setTimeout(() => clearBtn.classList.remove("armed"), 3000);
      return;
    }
    clearTimeout(armedTimer);
    clearBtn.classList.remove("armed");
    queueEl.querySelectorAll(".card").forEach((c, i) => { if (i < 12) tearAway(c, i * 70); });   // 最多演 12 張，避免長清單卡住 / animate at most 12 cards so a long list doesn't stall
    send({ type: "clear" });
  });

  /* ----------------------------------------------------------- 加歌 / Adding songs ----
     快速加歌的幾種方式：
     1. 輸入框：Enter 加到最後；Shift+Enter 或"下一首"按鈕插到最前面
     2. 在頁面任何地方 Ctrl+V，直接貼上網址／分享文字就加入
     3. 把瀏覽器裡的連結（或選取的文字）拖進頁面

     Ways to add a song quickly:
     1. The input box: Enter appends; Shift+Enter or the "next" button inserts at the front
     2. Press Ctrl+V anywhere on the page: a pasted URL / shared text is added directly
     3. Drag a link (or selected text) from the browser into the page */
  const input = $("#addInput"), detectEl = $("#detect");
  const TIP = "Enter 加到最後 · Shift+Enter 下一首 · 在頁面任何地方 Ctrl+V 貼上也行";

  /** 依輸入內容更新"辨識為…"提示 / Update the "Detected as ..." hint from the input's content. */
  function updateDetect() {
    const d = detect(input.value);
    detectEl.replaceChildren();
    if (!d) {
      detectEl.className = "detect tip";
      detectEl.textContent = TIP;
      return;
    }
    detectEl.className = "detect" + (d.k ? ` ${d.k}` : "");
    detectEl.append(el("span", "dot"), document.createTextNode(d.t));
  }
  input.addEventListener("input", updateDetect);
  updateDetect();

  /**
   * 送出加歌請求，在空分頁時會帶上 channel，伺服器就只會放進那個頻道
   * Send an "add" request. On an empty tab it carries `channel`, so the server puts the song into that channel only.
   * @param {string} query 網址／BV 號／關鍵字 / URL, BV id or keywords
   * @param {"end"|"next"|"now"} when 加到哪裡 / where to add
   * @param {boolean} quiet 不顯示"解析中"提示 / suppress the "resolving" toast
   */
  function addTrack(query, when = "end", quiet = false) {
    query = query.trim();
    if (!query) return false;
    send({ type: "add", query, when, ...(targetChannel ? { channel: targetChannel } : {}) });
    if (!quiet) toast(when === "end" ? "解析中，卡片稍後出現…" : "解析中，這首會插到最前面…");
    return true;
  }

  /** 送出輸入框內容並清空 / Submit the input box content and clear it. */
  function submitInput(when) {
    if (addTrack(input.value, when)) {
      input.value = "";
      updateDetect();
    }
  }
  $("#addForm").addEventListener("submit", (e) => { e.preventDefault(); submitInput(e.submitter && e.submitter.id === "btnNext" ? "next" : "end"); });
  $("#btnNext").addEventListener("click", () => submitInput("next"));
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.shiftKey) { e.preventDefault(); submitInput("next"); }
  });

  // 2. 在輸入框以外的地方貼上 = 直接加入 / pasting outside any input = add directly
  document.addEventListener("paste", (e) => {
    const tgt = e.target;
    if (tgt && (tgt.tagName === "INPUT" || tgt.tagName === "TEXTAREA" || tgt.isContentEditable)) return;
    const text = (e.clipboardData && e.clipboardData.getData("text")) || "";
    if (text.trim() && addTrack(text, "end", true)) { e.preventDefault(); toast("已貼上，解析中…"); }
  });

  // 3. 把連結／文字拖進頁面 / drag a link or text into the page
  document.addEventListener("dragover", (e) => {
    const types = e.dataTransfer && e.dataTransfer.types;
    if (types && (types.includes("text/uri-list") || types.includes("text/plain"))) e.preventDefault();
  });
  document.addEventListener("drop", (e) => {
    const dt = e.dataTransfer;
    if (!dt) return;
    const text = dt.getData("text/uri-list") || dt.getData("text/plain");
    if (text && text.trim()) { e.preventDefault(); addTrack(text.split("\n")[0], "end", true); toast("已加入拖進來的連結，解析中…"); }
  });

  /* ------------------------------------------------ 多播放器（分身）分頁 / Multi-player (clone) tabs ----
     同一個伺服器有多個播放器時（每個頻道一個），上方出現分頁，預設自動跟著"你所在的頻道"，點分頁可改看別的

     When a server has several players (one per channel), tabs appear on top. By default the view follows
     "the channel you are in"; click a tab to look at another one. */
  const playersBar = $("#playersBar");
  let playersSig = "";     // 上一次畫分頁列時的簽章，沒變就不重畫 / signature of the last tab-bar render; unchanged = no re-render
  let menuOpen = false;    // "＋ 加到頻道"選單是否展開 / is the "+ add to channel" menu open?

  /**
   * 頻道有播放器了（空分頁變成正式分頁）或頻道不見了 → 把空分頁整理掉；回傳是否需要重畫
   * A channel now has a player (the empty tab becomes a real tab) or the channel vanished -> tidy up the
   * empty tabs; returns whether the view needs a re-render.
   */
  function reconcileTabs(s) {
    const byId = new Map(s.channels.map((c) => [c.id, c]));
    let viewChanged = false;
    pendingTabs = pendingTabs.filter((t) => {
      const ch = byId.get(t.id);
      if (!ch) { if (targetChannel === t.id) { targetChannel = null; viewChanged = true; } return false; }
      if (ch.pid) {                                   // 第一首歌已經加進去、機器人進頻道了：空分頁變成正式分頁 / the first song was added and the bot entered the channel: the empty tab becomes a real one
        if (targetChannel === t.id) { targetChannel = null; viewChanged = true; send({ type: "select", pid: ch.pid }); }
        return false;
      }
      t.name = ch.name;
      return true;
    });
    return viewChanged;
  }

  /** 在選單選了一個頻道：立刻開成一個獨立的空分頁 / A channel was picked in the menu: open it right away as an independent empty tab. */
  function openTab(id) {
    const ch = state.channels.find((c) => c.id === id);
    if (!ch) return;
    if (!pendingTabs.some((t) => t.id === id)) pendingTabs.push({ id, name: ch.name });
    targetChannel = id; menuOpen = false; playersSig = "";
    refresh();
    input.focus();
  }
  /** 關閉一個空分頁 / Close an empty tab. */
  function closeTab(id) {
    pendingTabs = pendingTabs.filter((t) => t.id !== id);
    if (targetChannel === id) targetChannel = null;
    playersSig = "";
    refresh();
  }

  /** 重畫分頁列（正式分頁、空分頁、"＋ 加到頻道"選單、使用中數量）/ Re-render the tab bar (real tabs, empty tabs, the "+ add to channel" menu, the in-use counter). */
  function syncPlayers(s) {
    // 只有"剛好一個播放器、也沒有分身"的單純情況才不需要這一列
    // The bar is only unnecessary in the simple case "exactly one player and no clones".
    const show = s.players.length !== 1 || s.clones.total > 1 || pendingTabs.length > 0;
    playersBar.hidden = !show;
    if (!show) { playersSig = ""; targetChannel = null; return; }
    reconcileTabs(s);

    const free = s.channels.filter((c) => !c.pid && !pendingTabs.some((t) => t.id === c.id));   // 還沒有播放器、也還沒開分頁的語音頻道 / voice channels with no player and no tab yet
    const canAdd = s.clones.idle > 0 && free.length > 0 && !(s.limit && s.limit.reached);       // 還有閒置的機器人、且沒被卡頓偵測器暫時擋住 / an idle bot exists and the stutter detector isn't blocking new channels
    const sig = JSON.stringify([s.selected, targetChannel, menuOpen, s.players.map((p) => [p.pid, p.name, p.paused, !!p.title]),
      pendingTabs.map((t) => [t.id, t.name]), s.clones, s.limit && [s.limit.max, s.limit.reached], canAdd && free.map((c) => [c.id, c.name, c.members])]);
    if (sig === playersSig) return;
    playersSig = sig;

    // 正式分頁（每個播放器一個）/ real tabs (one per player)
    const chips = s.players.map((p) => {
      const b = el("button", `player-chip ${p.title ? (p.paused ? "paused" : "playing") : ""}`);
      b.type = "button";
      b.setAttribute("role", "tab");
      b.setAttribute("aria-selected", String(p.pid === s.selected && !targetChannel));
      b.title = p.title ? `${p.bot}：${p.title}` : p.bot;
      b.append(el("span", "dot"), el("span", "label", p.name), el("small", "", p.bot));
      b.addEventListener("click", () => { targetChannel = null; playersSig = ""; send({ type: "select", pid: p.pid }); refresh(); });
      return b;
    });

    // 還沒開始播放的頻道分頁：自己獨立的一頁，在這裡加歌只會進這個頻道
    // Tabs of channels that haven't started playing: each one is its own page, and songs added here go to this channel only.
    const empties = pendingTabs.map((t) => {
      const wrap = el("span", "tab-wrap");
      const b = el("button", "player-chip fresh");
      b.type = "button";
      b.setAttribute("role", "tab");
      b.setAttribute("aria-selected", String(targetChannel === t.id));
      b.title = `「${t.name}」還沒有開始播放：貼上網址加一首歌，機器人就會進去，而且不會影響其他頻道`;
      b.append(el("span", "dot"), el("span", "label", t.name), el("small", "", "尚未播放"));
      b.addEventListener("click", () => { targetChannel = t.id; playersSig = ""; refresh(); input.focus(); });
      const x = el("button", "tab-close");
      x.type = "button"; x.title = "關閉這個分頁"; x.setAttribute("aria-label", `關閉「${t.name}」分頁`);
      x.appendChild(icon("close"));
      x.addEventListener("click", (e) => { e.stopPropagation(); closeTab(t.id); });
      wrap.append(b, x);
      return wrap;
    });

    const nodes = [...chips, ...empties];
    if (canAdd) {
      // "＋ 加到頻道"按鈕與下拉選單 / the "+ add to channel" button and its dropdown
      const wrap = el("span", "chan-wrap");
      const add = el("button", "player-chip add", "＋ 加到頻道");
      add.type = "button";
      add.setAttribute("aria-haspopup", "menu");
      add.setAttribute("aria-expanded", String(menuOpen));
      add.title = "選一個還沒有播放器的語音頻道，會開成一個獨立的分頁（派一個閒置的機器人進去，不影響其他頻道）";
      add.addEventListener("click", (e) => { e.stopPropagation(); menuOpen = !menuOpen; playersSig = ""; syncPlayers(state); });
      wrap.appendChild(add);
      if (menuOpen) {
        const menu = el("div", "menu");
        menu.setAttribute("role", "menu");
        free.forEach((c) => {
          const it = el("button", "menu-item");
          it.type = "button";
          it.setAttribute("role", "menuitem");
          it.append(el("span", "", c.name), el("small", "", c.members ? `${c.members} 人` : "沒人"));
          it.addEventListener("click", (e) => { e.stopPropagation(); openTab(c.id); });
          menu.appendChild(it);
        });
        wrap.appendChild(menu);
      }
      nodes.push(wrap);
    }
    const info = el("span", "clones",
      s.players.length ? `播放器 ${s.clones.total - s.clones.idle}／${s.clones.total} 使用中` : "還沒有在播放：先選一個語音頻道");
    info.title = s.limit && s.limit.reached && s.limit.max < s.limit.cap
      ? `偵測到卡頓，同時播放上限已降為 ${s.limit.max} 個頻道`
      : s.clones.idle ? `還有 ${s.clones.idle} 個閒置，可接手新的頻道` : "全部使用中。要同時在更多頻道播放，需要再設定分身（見 README）";
    nodes.push(info);
    playersBar.replaceChildren(...nodes);
  }
  document.addEventListener("click", () => { if (menuOpen) { menuOpen = false; playersSig = ""; if (state) syncPlayers(state); } });   // 點旁邊就收起選單 / a click elsewhere closes the menu

  /* ----------------------------------------------------- 誰能控制 / Who may control ----
     只有"人在語音頻道裡"的人能控制播放；其他人唯讀（伺服器端也會擋，這裡只是讓畫面誠實）

     In voice mode only people inside a voice channel may control playback; everyone else is read-only
     (the server enforces it too; this just keeps the UI honest). */
  const permBanner = $("#permBanner"), limitBanner = $("#limitBanner");

  /** 卡頓偵測器降低了同時播放上限：把原因告訴大家 / The stutter detector lowered the simultaneous-stream cap: tell everyone why. */
  function syncLimit(s) {
    const note = s.limit && s.limit.notice;
    limitBanner.hidden = !note;
    if (note) setText(limitBanner, note);
  }
  /** 依權限切換唯讀樣式、提示列、拖曳功能與輸入框提示 / Apply the read-only style, banner, drag ability and input placeholder according to permissions. */
  function syncPerms(s) {
    const ro = !s.me.can_control;
    document.body.classList.toggle("readonly", ro);
    permBanner.hidden = !ro;
    if (ro) setText(permBanner, s.me.reason || "唯讀");
    sortQueue.option("disabled", ro || !!targetChannel);
    sortNow.option("disabled", ro || !!targetChannel);
    input.placeholder = ro
      ? "先加入語音頻道，才能加歌"
      : targetChannel
        ? `貼上網址，加到「${(pendingTabs.find((t) => t.id === targetChannel) || {}).name || "這個頻道"}」（只會進這個頻道）`
        : "貼上 Bilibili／YouTube 網址、BV 號，或輸入關鍵字";
  }

  /* ----------------------------------------------- Bilibili 帳號 / Bilibili account ----
     只有機器人擁有者看得到，QR 登入是 Bilibili 官方流程，機器人只保存登入後的 cookie（在執行機器人的這台電腦）

     Visible to the bot owner only. QR login is Bilibili's official flow; the bot stores only the resulting
     cookies (on the machine running the bot). */
  const biliBtn = $("#biliBtn"), biliDlg = $("#biliDialog");
  const bq = { box: $("#biliQrBox"), img: $("#biliQr"), status: $("#biliQrStatus"), acc: $("#biliAccount"), note: $("#biliNote"),
               start: $("#biliStart"), logout: $("#biliLogout") };
  let biliState = null, qrTimer = null;

  /** 把頭像放進方塊（Bilibili 圖床會縮成指定尺寸；失敗就用音符圖示）/ Put an avatar into a box (Bilibili's CDN resizes it; falls back to a note icon). */
  function avatar(box, url, px) {
    box.replaceChildren();
    if (url) {
      const img = new Image();
      img.referrerPolicy = "no-referrer"; img.decoding = "async"; img.alt = "";
      img.onerror = () => { img.remove(); box.appendChild(icon("note")); };
      img.src = /hdslb\.com/.test(url) && !url.includes("@") ? `${url}@${px}w_${px}h_1c.webp` : url;
      box.appendChild(img);
    } else {
      box.appendChild(icon("note"));
    }
  }

  /** 依快照更新頂部的 Bilibili 按鈕（只有有權限的人才看得到）/ Update the Bilibili button in the top bar from the snapshot (only visible to those allowed to manage it). */
  function syncBili(s) {
    biliState = s.bili;
    biliBtn.hidden = !s.bili.can_manage;
    if (!s.bili.can_manage) return;
    setText($("#biliTitle"), s.bili.logged_in ? s.bili.name : "未登入 Bilibili");
    setText($("#biliSub"), s.bili.logged_in ? `${s.bili.vip_label}　點此更換帳號` : "點此掃碼登入");
    avatar($("#biliAvatar"), s.bili.logged_in ? s.bili.face : "", 96);
    if (biliDlg.open) renderBiliDialog();
  }

  /** 重畫登入對話框的內容（帳號資訊、按鈕、說明文字）/ Re-render the login dialog (account info, buttons, notes). */
  function renderBiliDialog(extra) {
    const b = biliState || {};
    const scanning = !bq.box.hidden;
    bq.acc.hidden = !b.logged_in || scanning;
    if (b.logged_in) {
      avatar($("#biliAccAvatar"), b.face, 128);
      setText($("#biliAccName"), b.name);
      const vip = $("#biliAccVip");
      setText(vip, b.vip_label);
      vip.className = "pill " + (b.vip ? "src-bili" : "");
    }
    bq.logout.hidden = !b.logged_in || scanning;
    bq.start.hidden = scanning;
    setText(bq.start, b.logged_in ? "更換帳號（掃碼）" : "掃碼登入");

    const lines = [];
    if (b.logged_in && !b.vip) {
      lines.push("<b>一般會員的音質上限與未登入相同</b>（約 192 kbps AAC）。Hi-Res 無損與杜比是<b>大會員</b>專屬。");
    } else if (b.logged_in && b.vip) {
      lines.push("<b>大會員</b>：機器人會優先使用 Hi-Res 無損（FLAC）音軌，搭配 Opus 320～510 kbps 最接近原音。");
    } else {
      lines.push("登入後的主要好處：降低搜尋被限流（HTTP 412）的機率、能播放需要登入才能看的影片。");
    }
    lines.push("掃碼是 Bilibili 官方的登入流程，機器人不會接觸你的密碼；登入憑證只存在<b>執行機器人的這台電腦</b>，重開機器人仍會記住。");
    bq.note.innerHTML = lines.map((l) => `<p>${l}</p>`).join("");
    if (extra) bq.note.insertAdjacentHTML("afterbegin", `<p>${extra}</p>`);
  }

  /** 設定 QR 狀態文字與樣式 / Set the QR status text and style. */
  function setQrStatus(text, cls = "") { setText(bq.status, text); bq.status.className = "qr-status " + cls; }
  /** 停止倒數並收起 QR 區 / Stop the countdown and hide the QR area. */
  function stopQr() { clearInterval(qrTimer); qrTimer = null; bq.box.hidden = true; }

  /** 每秒更新"幾秒後過期"的倒數文字 / Update the "expires in N seconds" text every second. */
  function startQrCountdown(ttl) {
    clearInterval(qrTimer);
    const t0 = Date.now();
    qrTimer = setInterval(() => {
      const left = Math.max(0, ttl - Math.round((Date.now() - t0) / 1000));
      if (left > 0 && !bq.status.classList.contains("ok") && bq.status.dataset.mode !== "scanned") setText(bq.status, `請用 Bilibili App 掃描（${left} 秒後過期）`);
    }, 1000);
  }

  biliBtn.addEventListener("click", () => { stopQr(); renderBiliDialog(); biliDlg.showModal(); });
  $("#biliClose").addEventListener("click", () => { send({ type: "bili_login_cancel" }); stopQr(); biliDlg.close(); });
  biliDlg.addEventListener("cancel", () => { send({ type: "bili_login_cancel" }); stopQr(); });
  biliDlg.addEventListener("click", (e) => { if (e.target === biliDlg) { send({ type: "bili_login_cancel" }); stopQr(); biliDlg.close(); } });
  bq.start.addEventListener("click", () => {
    bq.box.hidden = false; bq.img.removeAttribute("src"); bq.img.classList.add("dim");
    bq.status.dataset.mode = "";
    setQrStatus("正在向 Bilibili 取得 QR 碼…");
    renderBiliDialog();
    send({ type: "bili_login_start" });
  });
  bq.logout.addEventListener("click", () => { send({ type: "bili_logout" }); });

  /** 處理伺服器回報的 QR 登入進度（bili_qr / bili_status）/ Handle QR-login progress sent by the server (bili_qr / bili_status). */
  function onBiliMessage(msg) {
    if (msg.type === "bili_qr") {
      bq.img.src = msg.img; bq.img.classList.remove("dim");
      setQrStatus("請用 Bilibili App 掃描"); startQrCountdown(msg.ttl);
    } else if (msg.type === "bili_status") {
      bq.status.dataset.mode = msg.status;
      if (msg.status === "scanned") setQrStatus("已掃描，請在手機上按「確認登入」", "ok");
      else if (msg.status === "expired") { bq.img.classList.add("dim"); setQrStatus("QR 碼已過期，請重新產生", "bad"); clearInterval(qrTimer); bq.start.hidden = false; setText(bq.start, "重新產生 QR 碼"); }
      else if (msg.status === "error") { bq.img.classList.add("dim"); setQrStatus(msg.text || "登入失敗", "bad"); clearInterval(qrTimer); bq.start.hidden = false; setText(bq.start, "再試一次"); }
      else if (msg.status === "ok") { stopQr(); toast(`登入成功：${msg.account ? msg.account.name : ""}`); renderBiliDialog(); }
    }
  }

  /* ------------------------------------------------------------ 連線 / Connection */
  // 開放模式下沒有 Discord 身分時，用一個自動產生的暱稱當"點歌：xxx"
  // In open mode without a Discord identity, an auto-generated nickname is used as "requested by: xxx".
  let myName = "訪客";
  try {
    myName = localStorage.getItem("mb_name") || "";
    if (!myName) { myName = `訪客${Math.floor(100 + Math.random() * 900)}`; localStorage.setItem("mb_name", myName); }
  } catch { /* 瀏覽器禁止儲存時就用預設 / storage blocked: use the default */ }

  let authFailed = false;   // 憑證被拒絕後不再重連 / once the token is rejected, stop reconnecting

  /**
   * 建立 WebSocket 連線並處理伺服器訊息；斷線會自動以遞增間隔重連（最多 8 秒）
   * Open the WebSocket and handle server messages; reconnects automatically with a growing delay (max 8 s).
   *
   * Server -> browser message types / 伺服器送來的訊息類型:
   *   state (full snapshot) | toast | bili_qr / bili_status | verified (device token) | revoked | error
   */
  function connect() {
    const params = new URLSearchParams({ n: myName });
    if (token) params.set("t", token);
    if (device) params.set("d", device);
    ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/${gid}?${params}`);
    ws.onopen = () => { retry = 0; };
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type === "state") render(msg.data);
      else if (msg.type === "toast") toast(msg.text);
      else if (msg.type === "bili_qr" || msg.type === "bili_status") onBiliMessage(msg);
      else if (msg.type === "verified") { saveDevice(msg.token); toast(`已確認身分：${msg.name}，這個瀏覽器會被記住`); }
      else if (msg.type === "revoked") { saveDevice(null); toast("你的裝置已被撤銷，請重新用 /help 的連結進來"); }
      else if (msg.type === "error") {
        if (msg.code === "auth") {          // 憑證無效：不要一直重連，直接告訴使用者怎麼拿新的 / invalid token: stop reconnecting and tell the user how to get a new one
          authFailed = true;
          try { localStorage.removeItem(TOKEN_KEY); } catch { /* 忽略 / ignore */ }
          $("#board").hidden = true; document.querySelector(".topbar").hidden = true;
          playersBar.hidden = true; permBanner.hidden = true; $("#gate").hidden = false;
        } else if (msg.code === "offline") {   // 中繼站在線、但家裡的機器人沒連上：保持連線，回來後會自動恢復 / the relay is up but the home bot isn't connected: stay connected, it recovers automatically
          document.body.classList.add("offline");
          setStatus("播放端離線", false);
          permBanner.hidden = false;
          setText(permBanner, msg.text);
        } else { setStatus(msg.text, false); toast(msg.text); }
      }
    };
    ws.onclose = () => {
      if (authFailed) return;
      setStatus("連線中斷，重新連線中…", false);
      setTimeout(connect, Math.min(1000 * 2 ** retry++, 8000));
    };
  }
  connect();
})();
