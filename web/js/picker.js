/* 沒指定伺服器時顯示的選單
   The server picker shown when the URL names no server */
import { $, el } from "./util.js";

/* ------------------------------------------- 沒指定伺服器：顯示選單 / No server in the URL: show a picker */
export function initPicker() {
  $("#board").hidden = true;
  document.querySelector(".topbar").hidden = true;
  $("#picker").hidden = false;
  fetch("/api/guilds").then((r) => r.json()).then((list) => {
    if (list.length === 1) { location.replace(`/g/${list[0].id}`); return; }   // 只有一個伺服器就直接進去 / only one server: go straight in
    const box = $("#pickerList");
    if (!list.length) box.textContent = T("noGuild");
    list.forEach((g) => {
      const a = el("a", "", g.name);
      a.href = `/g/${g.id}`;
      box.appendChild(a);
    });
  });
  return;
}
