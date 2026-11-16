/* 連線：WebSocket、重連、收到伺服器訊息、送出操作
   Connection: the WebSocket, reconnecting, server messages, sending actions */
import { onBiliMessage } from "./bili.js";
import { onSpotify } from "./spotify.js";
import { onLibrary, onLibrarySongs } from "./library.js";
import { permBanner } from "./perms.js";
import { announceWindow } from "./queuewindow.js";
import { render } from "./render.js";
import { S, TOKEN_KEY, gid, saveDevice } from "./store.js";
import { playersBar } from "./tabs.js";
import { $, setStatus, setText, toast } from "./util.js";

let retry = 0;   // 重連次數，用來算等待時間 / reconnect count, drives the delay

export const OK_ON_EMPTY_TAB = new Set(["add", "select", "quality", "queue_window", "bili_login_start", "bili_login_cancel", "bili_logout"]);

/** 送一則訊息給伺服器（連線中才送；空分頁會擋下不允許的操作）/ Send a message to the server (only while connected; empty tabs block disallowed actions). */
export const send = (obj) => {
  if (S.targetChannel && !OK_ON_EMPTY_TAB.has(obj.type) && !String(obj.type).startsWith("lib_") && !String(obj.type).startsWith("sp_")) { toast(T("emptyChannelToast")); return; }
  if (S.ws && S.ws.readyState === WebSocket.OPEN) S.ws.send(JSON.stringify(obj));
};

/* ------------------------------------------------------------ 連線 / Connection */
// 沒有 Discord 身分時（例如本機直接開），用一個自動產生的暱稱當"點歌：xxx"
// Without a Discord identity (e.g. opened directly on the local machine), an auto-generated nickname is used as "requested by: xxx".
let myName = T("guest");
try {
  myName = localStorage.getItem("mb_name") || "";
  if (!myName) { myName = T("guestN", { n: Math.floor(100 + Math.random() * 900) }); localStorage.setItem("mb_name", myName); }
} catch { /* 瀏覽器禁止儲存時就用預設 / storage blocked: use the default */ }

let authFailed = false;   // 憑證被拒絕後不再重連 / once the token is rejected, stop reconnecting

/**
 * 建立 WebSocket 連線並處理伺服器訊息；斷線會自動以遞增間隔重連（最多 8 秒）
 * Open the WebSocket and handle server messages; reconnects automatically with a growing delay (max 8 s).
 *
 * Server -> browser message types / 伺服器送來的訊息類型:
 *   state (full snapshot) | toast | bili_qr / bili_status | verified (device token) | revoked | error
 */
export function connect() {
  const params = new URLSearchParams({ n: myName });
  if (S.token) params.set("t", S.token);
  if (S.device) params.set("d", S.device);
  S.ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/${gid}?${params}`);
  S.ws.onopen = () => { retry = 0; announceWindow(); send({ type: "sp_status" }); };
  S.ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "state") render(msg.data);
    else if (msg.type === "toast") toast(msg.text);
    else if (msg.type === "library") onLibrary(msg);
    else if (msg.type === "spotify") onSpotify(msg);
    else if (msg.type === "library_songs") onLibrarySongs(msg);
    else if (msg.type === "bili_qr" || msg.type === "bili_status") onBiliMessage(msg);
    else if (msg.type === "verified") { saveDevice(msg.token); toast(T("verified", { name: msg.name })); }
    else if (msg.type === "revoked") { saveDevice(null); toast(T("revoked")); }
    else if (msg.type === "error") {
      if (msg.code === "auth") {          // 憑證無效：不要一直重連，直接告訴使用者怎麼拿新的 / invalid token: stop reconnecting and tell the user how to get a new one
        authFailed = true;
        try { localStorage.removeItem(TOKEN_KEY); } catch { /* 忽略 / ignore */ }
        $("#board").hidden = true; document.querySelector(".topbar").hidden = true;
        playersBar.hidden = true; permBanner.hidden = true; $("#gate").hidden = false;
      } else if (msg.code === "offline") {   // 中繼站在線、但家裡的機器人沒連上：保持連線，回來後會自動恢復 / the relay is up but the home bot isn't connected: stay connected, it recovers automatically
        document.body.classList.add("offline");
        setStatus(T("workerOffline"), false);
        permBanner.hidden = false;
        setText(permBanner, msg.text);
      } else { setStatus(msg.text, false); toast(msg.text); }
    }
  };
  S.ws.onclose = () => {
    if (authFailed) return;
    setStatus(T("reconnecting"), false);
    setTimeout(connect, Math.min(1000 * 2 ** retry++, 8000));
  };
}
