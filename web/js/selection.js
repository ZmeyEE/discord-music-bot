/* 待播清單的選取模式與"加入歌單"：選幾首歌存成歌單，或把一首歌加進某張歌單
   Select mode of the queue and "add to a playlist": pick songs and save them as a playlist, or add one song to a playlist */
import { askName, pickPlaylist } from "./libdialogs.js";
import { fetchTree } from "./library.js";
import { queuePanel, queueEl } from "./dom.js";
import { send } from "./net.js";
import { S } from "./store.js";
import { $, setText } from "./util.js";

const btn = $("#btnSelect"), bar = $("#selBar"), info = $("#selCount"), saveBtn = $("#selSave");

/** 更新選取列的文字與卡片的勾勾 / Refresh the select bar and the ticks on the cards. */
function refresh() {
  const n = S.selected.size;
  queuePanel.classList.toggle("selecting", S.selecting);
  btn.classList.toggle("on", S.selecting);
  btn.setAttribute("aria-pressed", String(S.selecting));
  setText(info, T("selCount", { n }));
  setText(saveBtn, T("selSave", { n }));
  saveBtn.disabled = n === 0;
  for (const c of queueEl.querySelectorAll(".card")) c.classList.toggle("selected", S.selected.has(c.dataset.id));
}

/** 開關選取模式 / Toggle select mode. */
function toggle(on = !S.selecting) {
  S.selecting = on;
  if (!on) S.selected.clear();
  refresh();
}

btn.addEventListener("click", () => toggle());
$("#selNone").addEventListener("click", () => toggle(false));
$("#selAll").addEventListener("click", () => {
  for (const t of (S.state && S.state.queue) || []) S.selected.add(t.id);
  refresh();
});
saveBtn.addEventListener("click", async () => {
  if (!S.selected.size) return;
  const name = await askName({ title: T("saveAsName"), value: T("libNewPlaylistDef") });
  if (name == null) return;
  send({ type: "lib_save", name, ids: [...S.selected] });
  toggle(false);
});

// 選取模式下點卡片 = 勾選／取消（點卡片上的按鈕不算）/ in select mode a click on a card ticks it (clicks on its buttons don't count)
queueEl.addEventListener("click", (e) => {
  if (!S.selecting || e.target.closest(".actions")) return;
  const card = e.target.closest(".card");
  if (!card) return;
  const id = card.dataset.id;
  if (S.selected.has(id)) S.selected.delete(id); else S.selected.add(id);
  refresh();
});

// 卡片右上角的"加入歌單"：選一張歌單（或新建）再送出 / the "add to a playlist" button on a card: pick a playlist (or create one), then send
document.addEventListener("mb:add-to-list", async (e) => {
  const ids = e.detail.ids;
  const tree = await fetchTree();
  const pick = await pickPlaylist(tree);
  if (!pick) return;
  if (pick.create) {
    const name = await askName({ title: T("saveAsName"), value: T("libNewPlaylistDef") });
    if (name != null) send({ type: "lib_save", name, ids });
  } else send({ type: "lib_add", playlist: pick.playlist, ids });
});

// 清單重畫後（虛擬清單換了一批卡片）把勾勾補回去 / after the list is redrawn (the virtual list swapped cards) put the ticks back
new MutationObserver(() => { if (S.selecting) refresh(); }).observe(queueEl, { childList: true });
