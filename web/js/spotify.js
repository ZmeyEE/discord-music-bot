/* Spotify 帳號連結：按鈕（在 Bilibili 按鈕上方）、授權視窗、狀態
   Spotify account link: the button (above the Bilibili one), the authorisation dialog, the state
   伺服器端是 musicbot/hub/spotify.py；列出自己的歌單在 libspotify.js
   (the server side is musicbot/hub/spotify.py; listing one's own playlists is libspotify.js) */
import { send } from "./net.js";
import { $, setText } from "./util.js";

const btn = $("#spBtn"), sub = $("#spSub"), dlg = $("#spDialog");
const stateA = $("#spUnlinked"), stateB = $("#spLinked"), stateC = $("#spUnset"), paste = $("#spPaste"), how = $("#spHow");

/** 目前的 Spotify 狀態（伺服器告訴我們的）/ The current Spotify state (as the server told us). */
export const SP = { known: false, enabled: false, canSetup: false, linked: false, name: "", redirect: "", playlists: null };

/** 伺服器回了 Spotify 狀態 / The server sent the Spotify state. */
export function onSpotify(msg) {
  const d = msg.data;
  Object.assign(SP, { known: true, enabled: d.enabled, canSetup: !!d.can_setup, linked: d.linked, name: d.name, redirect: d.redirect });
  if (!d.linked) SP.playlists = null;
  if (d.playlists) SP.playlists = d.playlists;
  if (d.auth_url) window.open(d.auth_url, "_blank", "noopener");      // 在新分頁打開 Spotify 的同意頁 / Spotify's consent page opens in a new tab
  draw();
  document.dispatchEvent(new CustomEvent("mb:spotify"));
}

/** 按鈕與視窗依狀態重畫 / Redraw the button and dialog from the state. */
function draw() {
  setText($("#spTitle"), T("spTitle"));
  setText(sub, SP.linked ? T("spLinked", { name: SP.name }) : T(SP.known && !SP.enabled ? "spUnsetSub" : "spNotLinked"));
  btn.classList.toggle("linked", SP.linked);
  stateA.hidden = SP.linked || !SP.enabled;
  stateC.hidden = SP.enabled;
  stateB.hidden = !SP.linked;
  how.textContent = T("spHow", { redirect: SP.redirect });
  $("#spUnsetText").textContent = T(SP.canSetup ? "spUnsetOwner" : "spUnset", { redirect: SP.redirect });
  $("#spSetup").hidden = !SP.canSetup;
  setText($("#spName"), SP.name);
}

btn.addEventListener("click", () => { draw(); dlg.showModal(); send({ type: "sp_status" }); });
$("#spClose").addEventListener("click", () => dlg.close());
$("#spGo").addEventListener("click", () => send({ type: "sp_connect" }));
$("#spDone").addEventListener("click", () => {
  const text = paste.value.trim();
  if (text) { send({ type: "sp_finish", text }); paste.value = ""; }
});
$("#spSave").addEventListener("click", () => {
  const id = $("#spClientId").value.trim();
  if (id) { send({ type: "sp_setup", client_id: id }); $("#spClientId").value = ""; }
});
$("#spLogout").addEventListener("click", () => send({ type: "sp_logout" }));
$("#spOpenLists").addEventListener("click", () => { dlg.close(); document.dispatchEvent(new CustomEvent("mb:open-spotify-lists")); });
