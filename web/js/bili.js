/* Bilibili 帳號：掃碼登入視窗
   Bilibili account: the QR login dialog */
import { send } from "./net.js";
import { $, icon, setText, toast } from "./util.js";

/* ----------------------------------------------- Bilibili 帳號 / Bilibili account ----
   只有機器人擁有者看得到，QR 登入是 Bilibili 官方流程，機器人只保存登入後的 cookie（在執行機器人的這台電腦）

   Visible to the bot owner only. QR login is Bilibili's official flow; the bot stores only the resulting
   cookies (on the machine running the bot). */
export const biliBtn = $("#biliBtn"), biliDlg = $("#biliDialog");
export const bq = { box: $("#biliQrBox"), img: $("#biliQr"), status: $("#biliQrStatus"), acc: $("#biliAccount"), note: $("#biliNote"),
             start: $("#biliStart"), logout: $("#biliLogout") };
let biliState = null, qrTimer = null;

/** 把頭像放進方塊（Bilibili 圖床會縮成指定尺寸；失敗就用音符圖示）/ Put an avatar into a box (Bilibili's CDN resizes it; falls back to a note icon). */
export function avatar(box, url, px) {
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
export function syncBili(s) {
  biliState = s.bili;
  biliBtn.hidden = !s.bili.can_manage;
  if (!s.bili.can_manage) return;
  setText($("#biliTitle"), s.bili.logged_in ? s.bili.name : T("biliLoggedOut"));
  setText($("#biliSub"), s.bili.logged_in ? T("biliSwap", { vip: s.bili.vip_label }) : T("biliClickScan"));
  avatar($("#biliAvatar"), s.bili.logged_in ? s.bili.face : "", 96);
  if (biliDlg.open) renderBiliDialog();
}

/** 重畫登入對話框的內容（帳號資訊、按鈕、說明文字）/ Re-render the login dialog (account info, buttons, notes). */
export function renderBiliDialog(extra) {
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
  setText(bq.start, b.logged_in ? T("biliSwapBtn") : T("scanLogin"));

  const lines = [];
  if (b.logged_in && !b.vip) {
    lines.push(T("biliNote1"));
  } else if (b.logged_in && b.vip) {
    lines.push(T("biliNote2"));
  } else {
    lines.push(T("biliNote3"));
  }
  lines.push(T("biliNote4"));
  bq.note.innerHTML = lines.map((l) => `<p>${l}</p>`).join("");
  if (extra) bq.note.insertAdjacentHTML("afterbegin", `<p>${extra}</p>`);
}

/** 設定 QR 狀態文字與樣式 / Set the QR status text and style. */
export function setQrStatus(text, cls = "") { setText(bq.status, text); bq.status.className = "qr-status " + cls; }
/** 停止倒數並收起 QR 區 / Stop the countdown and hide the QR area. */
export function stopQr() { clearInterval(qrTimer); qrTimer = null; bq.box.hidden = true; }

/** 每秒更新"幾秒後過期"的倒數文字 / Update the "expires in N seconds" text every second. */
export function startQrCountdown(ttl) {
  clearInterval(qrTimer);
  const t0 = Date.now();
  qrTimer = setInterval(() => {
    const left = Math.max(0, ttl - Math.round((Date.now() - t0) / 1000));
    if (left > 0 && !bq.status.classList.contains("ok") && bq.status.dataset.mode !== "scanned") setText(bq.status, T("qrScanLeft", { n: left }));
  }, 1000);
}

biliBtn.addEventListener("click", () => { stopQr(); renderBiliDialog(); biliDlg.showModal(); });
$("#biliClose").addEventListener("click", () => { send({ type: "bili_login_cancel" }); stopQr(); biliDlg.close(); });
biliDlg.addEventListener("cancel", () => { send({ type: "bili_login_cancel" }); stopQr(); });
biliDlg.addEventListener("click", (e) => { if (e.target === biliDlg) { send({ type: "bili_login_cancel" }); stopQr(); biliDlg.close(); } });
bq.start.addEventListener("click", () => {
  bq.box.hidden = false; bq.img.removeAttribute("src"); bq.img.classList.add("dim");
  bq.status.dataset.mode = "";
  setQrStatus(T("qrFetching"));
  renderBiliDialog();
  send({ type: "bili_login_start" });
});
bq.logout.addEventListener("click", () => { send({ type: "bili_logout" }); });

/** 處理伺服器回報的 QR 登入進度（bili_qr / bili_status）/ Handle QR-login progress sent by the server (bili_qr / bili_status). */
export function onBiliMessage(msg) {
  if (msg.type === "bili_qr") {
    bq.img.src = msg.img; bq.img.classList.remove("dim");
    setQrStatus(T("biliScan")); startQrCountdown(msg.ttl);
  } else if (msg.type === "bili_status") {
    bq.status.dataset.mode = msg.status;
    if (msg.status === "scanned") setQrStatus(T("qrScanned"), "ok");
    else if (msg.status === "expired") { bq.img.classList.add("dim"); setQrStatus(T("qrExpired"), "bad"); clearInterval(qrTimer); bq.start.hidden = false; setText(bq.start, T("qrRegen")); }
    else if (msg.status === "error") { bq.img.classList.add("dim"); setQrStatus(msg.text || T("loginFailed"), "bad"); clearInterval(qrTimer); bq.start.hidden = false; setText(bq.start, T("retry")); }
    else if (msg.status === "ok") { stopQr(); toast(T("loginOk", { name: msg.account ? msg.account.name : "" })); renderBiliDialog(); }
  }
}
