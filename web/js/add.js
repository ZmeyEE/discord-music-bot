/* 加歌：輸入框、貼上、拖進連結、辨識提示
   Adding songs: the input box, pasting, dropped links, the detection hint */
import { send } from "./net.js";
import { S } from "./store.js";
import { $, detect, el, toast } from "./util.js";

/* ----------------------------------------------------------- 加歌 / Adding songs ----
   快速加歌的幾種方式：
   1. 輸入框：Enter 加到最後；Shift+Enter 或"下一首"按鈕插到最前面
   2. 在頁面任何地方 Ctrl+V，直接貼上網址／分享文字就加入
   3. 把瀏覽器裡的連結（或選取的文字）拖進頁面

   Ways to add a song quickly:
   1. The input box: Enter appends; Shift+Enter or the "next" button inserts at the front
   2. Press Ctrl+V anywhere on the page: a pasted URL / shared text is added directly
   3. Drag a link (or selected text) from the browser into the page */
export const input = $("#addInput"), detectEl = $("#detect");
export const TIP = T("keyTip");

/** 依輸入內容更新"辨識為…"提示 / Update the "Detected as ..." hint from the input's content. */
export function updateDetect() {
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
export function addTrack(query, when = "end", quiet = false) {
  query = query.trim();
  if (!query) return false;
  send({ type: "add", query, when, ...(S.targetChannel ? { channel: S.targetChannel } : {}) });
  if (!quiet) toast(when === "end" ? T("resolvingEnd") : T("resolvingNext"));
  return true;
}

/** 送出輸入框內容並清空 / Submit the input box content and clear it. */
export function submitInput(when) {
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
  if (text.trim() && addTrack(text, "end", true)) { e.preventDefault(); toast(T("pasted")); }
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
  if (text && text.trim()) { e.preventDefault(); addTrack(text.split("\n")[0], "end", true); toast(T("dropped")); }
});
