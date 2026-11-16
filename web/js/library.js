/* 我的歌單：視窗、資料夾導覽、歌單／資料夾卡片、選取、播放
   My library: the dialog, folder navigation, playlist / folder cards, selecting, playing
   伺服器端是 musicbot/hub/library.py；歌曲列表在 libsongs.js，小視窗在 libdialogs.js
   (the server side is musicbot/hub/library.py; the song rows are in libsongs.js, the small dialogs in libdialogs.js) */
import { askName, closeMenu, showMenu } from "./libdialogs.js";
import { closeSongs, openSongs, songsView } from "./libsongs.js";
import { drawSpotify, loadSpotifyLists } from "./libspotify.js";
import { send } from "./net.js";
import { SP } from "./spotify.js";
import { S } from "./store.js";
import { $, REDUCED_MOTION, el, icon, toast } from "./util.js";

const dlg = $("#libDialog"), body = $("#libBody"), crumbs = $("#libCrumbs"), bar = $("#libBar"), box = $("#libBox");

/** 這個視窗的狀態 / The state of this dialog. */
export const L = {
  tree: null,             // 伺服器給的整棵樹摘要 / the outline of the whole tree from the server
  path: ["root"],         // 現在在哪一層：資料夾 id 由外到內 / where we are: folder ids from the outside in
  playlist: null,         // 正在看的歌單 id（null = 看資料夾）/ the playlist being viewed (null = viewing a folder)
  spotify: false,         // 是否在看自己的 Spotify 歌單 / viewing one's own Spotify playlists
  selecting: false,
  picked: new Set(),      // 選取模式下選了的項目 id / ids picked in select mode
  waiting: [],            // 等樹回來才做的事 / things waiting for the tree to arrive
};

/** 在樹裡用 id 找節點 / Find a node of the tree by id. */
export function nodeOf(id, node = L.tree) {
  if (!node) return null;
  if (node.id === id) return node;
  for (const c of node.children || []) { const f = nodeOf(id, c); if (f) return f; }
  return null;
}

/** 現在看的資料夾（被刪掉了就退到根）/ The folder being viewed (falls back to the root when it was deleted). */
function current() {
  while (L.path.length > 1 && !nodeOf(L.path[L.path.length - 1])) L.path.pop();
  return nodeOf(L.path[L.path.length - 1]) || L.tree;
}

/** 向伺服器要樹；回傳 Promise，樹到了就完成 / Ask the server for the tree; the promise settles when it arrives. */
export function fetchTree() {
  return new Promise((resolve) => { L.waiting.push(resolve); send({ type: "lib_get" }); });
}

/** 伺服器回了新的樹 / The server sent a new tree. */
export function onLibrary(msg) {
  L.tree = msg.data.tree;
  const waiting = L.waiting; L.waiting = [];
  waiting.forEach((r) => r(L.tree));
  if (dlg.open) {
    if (L.playlist) songsView.reload();               // 歌單的內容可能變了 / the playlist may have changed
    render();
  }
}

/** 伺服器回了一張歌單的歌 / The server sent the songs of a playlist. */
export function onLibrarySongs(msg) { if (dlg.open) songsView.onSongs(msg.data); }

const enter = (node) => { if (!REDUCED_MOTION) { node.classList.add("enter"); setTimeout(() => node.classList.remove("enter"), 320); } };

/** 打開歌單視窗 / Open the library dialog. */
export async function openLibrary() {
  L.selecting = false; L.picked.clear(); L.playlist = null; L.spotify = false;
  if (!dlg.open) dlg.showModal();
  if (!L.tree) await fetchTree(); else send({ type: "lib_get" });
  render();
}

/** 進到某個資料夾或歌單，帶一點打開的動畫 / Go into a folder or playlist with a little opening animation. */
function enterNode(card, node) {
  const go = () => {
    L.picked.clear();
    if (node.type === "folder") { L.path.push(node.id); L.playlist = null; }
    else { L.playlist = node.id; openSongs(node); }
    render(true);
  };
  if (REDUCED_MOTION) go(); else { card.classList.add("opening"); setTimeout(go, 170); }
}

/** 往上一層（歌單 → 資料夾 → 上層資料夾）/ Go up one level (playlist -> folder -> parent folder). */
function up() {
  L.picked.clear();
  if (L.spotify) L.spotify = false;
  else if (L.playlist) { L.playlist = null; closeSongs(); } else if (L.path.length > 1) L.path.pop();
  render(true);
}

/** 麵包屑：我的歌單 / 華語 / 抒情 / The breadcrumbs. */
function drawCrumbs() {
  crumbs.replaceChildren();
  const parts = L.path.map((id, i) => ({ id, label: i === 0 ? T("libRoot") : (nodeOf(id) || {}).name || "", depth: i }));
  if (L.playlist) parts.push({ id: L.playlist, label: (nodeOf(L.playlist) || {}).name || "", depth: -1 });
  if (L.spotify) parts.push({ id: "spotify", label: "Spotify", depth: -1 });
  parts.forEach((p, i) => {
    if (i) crumbs.appendChild(el("span", "sep", "›"));
    const b = el("button", "", p.label);
    b.type = "button";
    b.addEventListener("click", () => {
      if (p.depth < 0) return;
      L.path.length = p.depth + 1; L.playlist = null; L.spotify = false; closeSongs(); L.picked.clear(); render(true);
    });
    crumbs.appendChild(b);
  });
}

/** 工具列：平常是新增／貼連結／選取，選取模式變成建立資料夾／刪除／取消 / The toolbar: add / paste a link / select, or in select mode make folder / delete / cancel. */
function drawBar() {
  bar.replaceChildren();
  const btn = (label, cls, run) => { const b = el("button", cls, label); b.type = "button"; b.addEventListener("click", run); bar.appendChild(b); return b; };
  const folder = current();
  if (L.spotify) return;                                   // Spotify 歌單只能點一張匯入，沒有別的工具 / Spotify playlists only take a click to import, no other tools
  if (L.selecting) {
    const n = L.picked.size;
    if (!L.playlist) btn(T("libGroup", { n }), "btn-primary", async () => {
      if (!n) return;
      const name = await askName({ title: T("libFolderName"), value: T("libNewFolderDef") });
      if (name != null) { send({ type: "lib_folder", name, ids: [...L.picked] }); exitSelect(); }
    });
    btn(T("libDelete", { n }), "btn-ghost danger", () => deleteMany());
    btn(T("libCancel"), "btn-ghost", exitSelect);
    return;
  }
  if (!L.playlist) {
    btn(T("libNewPlaylist"), "btn-ghost", async () => {
      const name = await askName({ title: T("libPlaylistName"), value: T("libNewPlaylistDef") });
      if (name != null) send({ type: "lib_playlist", name, parent: folder.id });
    });
    btn(T("libNewFolder"), "btn-ghost", async () => {
      const name = await askName({ title: T("libFolderName"), value: T("libNewFolderDef") });
      if (name != null) send({ type: "lib_folder", name, parent: folder.id });
    });
  }
  btn(T("libLink"), "btn-ghost", async () => {
    const url = await askName({ title: T("libLinkTitle"), placeholder: T("libLinkPh"), ok: T("libLinkOk") });
    if (!url) return;
    if (L.playlist) send({ type: "lib_add_link", url, playlist: L.playlist });
    else send({ type: "lib_add_link", url, parent: folder.id, name: url.slice(0, 30) });
  });
  btn(T("libSelect"), "btn-ghost", () => { L.selecting = true; render(); });
  if (SP.linked && !L.playlist) btn(T("spLists"), "btn-ghost", () => { L.spotify = true; loadSpotifyLists(); render(true); });
  if (L.playlist) {
    btn(T("libPlay"), "btn-primary", (e) => playMenu(e.currentTarget, nodeOf(L.playlist)));
  }
}

const exitSelect = () => { L.selecting = false; L.picked.clear(); render(); };

/** 刪除選取的項目（要確認）/ Delete the picked items (with a confirmation). */
function deleteMany() {
  if (!L.picked.size) return;
  if (L.playlist) {                                   // 歌單裡選的是歌，不是資料夾：從歌單移除 / in a playlist the picks are songs: remove them from it
    send({ type: "lib_remove_songs", playlist: L.playlist, indexes: [...L.picked].map(Number) });
    exitSelect();
    return;
  }
  if (!confirmNow()) return;
  send({ type: "lib_delete", ids: [...L.picked] });
  exitSelect();
}

/** 刪除前的確認：3 秒內再按一次才真的刪，不用 window.confirm（它會卡住分頁）/ A confirmation without window.confirm (which freezes the tab): press the same thing twice within 3 s. */
let armedUntil = 0;
function confirmNow() {
  if (performance.now() < armedUntil) { armedUntil = 0; return true; }
  armedUntil = performance.now() + 3000;
  toast(T("libDeleteConfirm"));
  return false;
}

/** 播放選單：資料夾多兩個循環選項 / The play menu: folders get two extra loop options. */
function playMenu(anchor, node) {
  const play = (when, scope = "off") => {
    send({ type: "lib_play", id: node.id, when, scope, channel: S.targetChannel || undefined });
    dlg.close();
  };
  const items = [
    { label: T("libPlayEnd"), run: () => play("end") },
    { label: T("libPlayReplace"), run: () => play("replace") },
    { label: T("libPlayNext"), run: () => play("next") },
  ];
  if (node.type === "folder") {
    items.push({ label: null });
    items.push({ label: T("libLoopFolder"), run: () => play("replace", "folder") });
    items.push({ label: T("libLoopFolders"), run: () => play("replace", "folders") });
  }
  showMenu(anchor, box, items);
}

/** 一張資料夾或歌單卡片 / One folder or playlist card. */
function makeCard(node) {
  const card = el("div", `lib-card ${node.type}`);
  card.tabIndex = 0;
  card.dataset.id = node.id;
  const art = el("div", "lib-art");
  if (node.type === "folder") art.appendChild(icon("folder"));
  else if (node.covers && node.covers.length) {
    const m = el("div", node.covers.length < 2 ? "lib-mosaic one" : "lib-mosaic");
    for (const url of node.covers) {
      const img = new Image(); img.src = url; img.alt = ""; img.referrerPolicy = "no-referrer"; img.loading = "lazy"; img.draggable = false;
      img.onerror = () => img.remove();
      m.appendChild(img);
    }
    art.appendChild(m);
  } else art.appendChild(icon("note"));
  const tick = el("span", "lib-tick"); tick.appendChild(icon("check"));
  const act = el("div", "lib-act");
  const small = (name, label, cls, run) => {
    const b = el("button", cls); b.type = "button"; b.title = label; b.setAttribute("aria-label", label); b.appendChild(icon(name));
    b.addEventListener("click", (e) => { e.stopPropagation(); run(b); });
    act.appendChild(b);
  };
  small("play", T("libPlay"), "", (b) => playMenu(b, node));
  small("edit", T("libRename"), "", async () => {
    const name = await askName({ title: T("libRenameTitle"), value: node.name });
    if (name) send({ type: "lib_rename", id: node.id, name });
  });
  small("close", T("libDelete", { n: 1 }), "x", () => { if (confirmNow()) send({ type: "lib_delete", ids: [node.id] }); });
  card.append(art, tick, act, el("div", "lib-name", node.name), el("div", "lib-sub", T("libSongs", { n: node.count })));
  card.title = node.name;
  const choose = () => {
    if (L.selecting) {
      if (L.picked.has(node.id)) L.picked.delete(node.id); else L.picked.add(node.id);
      card.classList.toggle("selected", L.picked.has(node.id));
      drawBar();
    } else enterNode(card, node);
  };
  card.addEventListener("click", choose);
  card.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); choose(); } });
  if (L.picked.has(node.id)) card.classList.add("selected");
  return card;
}

/** 畫出目前這一層 / Draw the current level. */
export function render(animate = false) {
  closeMenu();
  if (!L.tree) return;
  box.classList.toggle("lib-selecting", L.selecting);
  drawCrumbs();
  drawBar();
  if (L.spotify) { drawSpotify(body, current().id); return; }
  if (L.playlist) { songsView.draw(body, nodeOf(L.playlist), L, animate && enter); return; }
  const folder = current();
  body.replaceChildren();
  const kids = folder.children || [];
  if (!kids.length) {
    const e = el("div", "lib-empty"); e.append(el("p", "", T("libEmpty")), el("p", "lib-sub", T("libEmptyHint"))); body.appendChild(e); return;
  }
  const grid = el("div", "lib-grid");
  kids.forEach((n) => grid.appendChild(makeCard(n)));
  body.appendChild(grid);
  if (animate) enter(grid);
}

$("#btnLibrary").addEventListener("click", openLibrary);
document.addEventListener("mb:lib-bar", drawBar);
document.addEventListener("mb:spotify", () => { if (dlg.open && L.spotify) render(); });
document.addEventListener("mb:open-spotify-lists", async () => { await openLibrary(); L.spotify = true; loadSpotifyLists(); render(true); });
$("#libClose").addEventListener("click", () => dlg.close());
$("#libUp").addEventListener("click", up);
dlg.addEventListener("close", () => { L.selecting = false; L.picked.clear(); closeMenu(); });
