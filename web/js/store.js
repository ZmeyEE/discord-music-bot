/* ==========================================================================
   共用狀態：幾個模組都會讀寫的變數放在 S 這一個物件裡，其他模組一律用 S.xxx
   Shared state: variables several modules read and write live in the one object S; every other module uses S.xxx
   ========================================================================== */
const m = location.pathname.match(/^\/g\/(\d+)/);                   // 網址 /g/<伺服器 id> / URL pattern /g/<guild id>
export const gid = m ? m[1] : null;                                      // 目前看的伺服器 id，沒有就是選單頁 / the server id being viewed, null on the picker page

// 存取憑證：/help 給的連結帶 ?t=…；記在這台瀏覽器，並從網址列拿掉，避免被截圖或轉貼時外流
// Access token: the /help link carries ?t=...; it is kept in this browser and removed from the address bar so it doesn't leak.
export const TOKEN_KEY = `mb_token_${gid}`;
const urlToken = new URLSearchParams(location.search).get("t");
try {
  if (urlToken) {
    localStorage.setItem(TOKEN_KEY, urlToken);
    history.replaceState(null, "", location.pathname);
  }
} catch { /* 瀏覽器禁止儲存時，只在這次有效 / storage blocked: the token only works for this visit */ }

// 裝置憑證：在 Discord 驗證過後，主機發給這個瀏覽器的長憑證（主機只存它的雜湊）
// Device token: the long token the host hands to this browser after Discord verification (the host stores only its hash).
export const DEVICE_KEY = `mb_device_${gid}`;

export const S = {
  state: null,           // 最新的伺服器快照 / the latest server snapshot
  targetChannel: null,   // 目前正在看的空分頁（頻道 id）/ the empty tab being viewed (channel id)
  pendingTabs: [],       // 已開但還沒有開始播放的分頁 / tabs opened but not playing yet
  ws: null,              // WebSocket
  dragging: false,       // 拖曳卡片中不重畫 / no re-render while dragging a card
  seeking: false,        // 拖曳進度條中也不重畫 / no re-render while dragging the seek bar
  deferred: null,        // 拖曳中收到的最新快照，放開後再套用 / the newest snapshot received mid-drag, applied afterwards
  recvAt: 0,             // 收到快照的時間，用來在本地推算播放進度 / when the snapshot arrived, to extrapolate the position
  nowRefs: null,         // "正在播放"卡片裡常更新的節點 / nodes inside the now-playing card that are updated often
  handled: new Set(),    // 這次拖曳已處理過的卡片 / cards already handled in this drag
  token: urlToken || (() => { try { return localStorage.getItem(TOKEN_KEY); } catch { return null; } })(),
  device: (() => { try { return localStorage.getItem(DEVICE_KEY); } catch { return null; } })(),
};

export const saveDevice = (t) => { S.device = t; try { t ? localStorage.setItem(DEVICE_KEY, t) : localStorage.removeItem(DEVICE_KEY); } catch { /* 忽略 / ignore */ } };
