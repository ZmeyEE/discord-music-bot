/* 我的歌單用的小視窗：問名字、選歌單、播放選單
   Small dialogs of the library: asking a name, picking a playlist, the play menu */
import { $, el } from "./util.js";

const nameDlg = $("#nameDialog"), nameForm = $("#nameForm"), nameInput = $("#nameInput"), nameTitle = $("#nameTitle"), nameOk = $("#nameOk");
const pickDlg = $("#pickDialog"), pickList = $("#pickList");

/**
 * 問一個名字（或一段文字），回傳輸入的內容；按取消／Esc 回傳 null。不用 window.prompt，因為它會卡住整個分頁
 * Ask for a name (or some text); resolves to the text, or null on cancel / Esc. Not window.prompt, which would freeze the whole tab.
 * @param {{title: string, value?: string, placeholder?: string, ok?: string}} o
 */
export function askName({ title, value = "", placeholder = "", ok = T("libOk") }) {
  return new Promise((resolve) => {
    nameTitle.textContent = title;
    nameOk.textContent = ok;
    nameInput.value = value;
    nameInput.placeholder = placeholder;
    let answer = null;
    const done = () => { nameDlg.removeEventListener("close", done); resolve(answer); };
    nameDlg.addEventListener("close", done);
    nameForm.onsubmit = (e) => { e.preventDefault(); answer = nameInput.value.trim(); nameDlg.close(); };
    $("#nameCancel").onclick = () => nameDlg.close();
    nameDlg.showModal();
    nameInput.focus(); nameInput.select();
  });
}

/**
 * 從歌單樹挑一張歌單，回傳 { playlist: id } 或 { create: true }（要新建）；取消回傳 null
 * Pick a playlist from the tree: ``{ playlist: id }``, ``{ create: true }`` for a new one, or null on cancel.
 */
export function pickPlaylist(tree) {
  return new Promise((resolve) => {
    pickList.replaceChildren();
    let answer = null;
    const choose = (a) => { answer = a; pickDlg.close(); };
    const lists = [];
    (function walk(node, path) {
      for (const c of node.children || []) {
        if (c.type === "playlist") lists.push({ id: c.id, label: [...path, c.name].join(" / "), count: c.count });
        else walk(c, [...path, c.name]);
      }
    })(tree, []);
    const add = (label, count, a) => {
      const b = el("button", "", label);
      b.type = "button";
      if (count != null) b.appendChild(el("small", "", T("libSongs", { n: count })));
      b.addEventListener("click", () => choose(a));
      pickList.appendChild(b);
    };
    add(T("libPickNew"), null, { create: true });
    for (const l of lists) add(l.label, l.count, { playlist: l.id });
    if (!lists.length) pickList.appendChild(el("p", "lib-sub", T("libPickNone")));
    const done = () => { pickDlg.removeEventListener("close", done); resolve(answer); };
    pickDlg.addEventListener("close", done);
    $("#pickCancel").onclick = () => pickDlg.close();
    pickDlg.showModal();
  });
}

let menuEl = null;
/** 關掉現在開著的選單 / Close the menu that is open. */
export function closeMenu() { if (menuEl) { menuEl.remove(); menuEl = null; } }

/**
 * 在某個按鈕旁邊開一個選單；items 是 [{label, run}]，label 為 null 代表分隔線
 * Open a menu next to a button; items are ``[{label, run}]``, a null label is a separator.
 * @param {HTMLElement} anchor 按鈕 / the button
 * @param {HTMLElement} host   選單要放進哪個元素（要在 dialog 裡才看得到）/ where the menu goes (inside the dialog to be visible)
 */
export function showMenu(anchor, host, items) {
  closeMenu();
  menuEl = el("div", "lib-menu");
  for (const it of items) {
    if (it.label == null) { menuEl.appendChild(document.createElement("hr")); continue; }
    const b = el("button", "", it.label);
    b.type = "button";
    b.addEventListener("click", (e) => { e.stopPropagation(); closeMenu(); it.run(); });
    menuEl.appendChild(b);
  }
  host.appendChild(menuEl);
  const a = anchor.getBoundingClientRect(), h = host.getBoundingClientRect();
  const left = Math.min(a.left - h.left, h.width - menuEl.offsetWidth - 8);
  menuEl.style.left = `${Math.max(8, left)}px`;
  menuEl.style.top = `${Math.min(a.bottom - h.top + 4, h.height - menuEl.offsetHeight - 8)}px`;
  setTimeout(() => document.addEventListener("click", closeMenu, { once: true }), 0);
}
