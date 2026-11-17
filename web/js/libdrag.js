/* 我的歌單：拖曳。卡片／歌曲可以排序、拖到左邊的資料夾列（放在列的上緣／下緣＝插在那個位置，放在中間＝放進去）、拖到右上角的刪除區
   左邊的資料夾列本身也能拖
   My library: dragging. Cards / songs reorder; drop on the folder bar (top / bottom edge of a row = insert at that spot, middle = move inside) or on the trash at the top right.
   The rows of the folder bar can be dragged too.
   卡片用的是和待播清單同一個 SortableJS；放開時看指標在哪個元素上（有 data-drop 就是搬家，是 #libTrash 就是刪除）
   (cards use the same SortableJS as the queue; at release we look at the element under the pointer: data-drop = move, #libTrash = delete) */
import { common } from "./dragdrop.js";
import { send } from "./net.js";

const box = document.getElementById("libBox"), trash = document.getElementById("libTrash");
let inst = null, endedAt = 0, getTree = () => null, lastPt = null;

// SortableJS 的共用設定，但卡片是格狀排列，不能指定"直的"；而且視窗在最上層，浮動的卡片不能放在 body（會被蓋在視窗後面）
// Shared options, but the cards sit in a grid so the direction must not be forced; and the dialog is in the top layer, so the floating card can't live on body (it would hide behind the dialog)
const options = { ...common, fallbackOnBody: false };
delete options.direction;

/** 讓拖曳知道整棵樹（算插入位置用）/ Tell dragging about the whole tree (needed to work out where to insert). */
export const useTree = (fn) => { getTree = fn; };

/** 剛拖完嗎？放開手的那一下會多出一個 click，要忽略 / Did a drag just end? The release can add a click that must be ignored. */
export const justDragged = () => performance.now() - endedAt < 250;

/** 指標在這一列的哪個區域：資料夾上 1/4 = 插在它前面、下 1/4 = 插在它後面、中間 = 放進去；歌單沒有"放進去"，只分前後；根只能放進去
    Where the pointer is on a row: top quarter of a folder = before it, bottom quarter = after it, the middle = inside; a playlist only has before / after; the root only takes "inside". */
function zoneOf(row, y) {
  if (row.dataset.root) return "into";
  const r = row.getBoundingClientRect(), f = (y - r.top) / (r.height || 1);
  if (row.dataset.kind === "folder") return f < 0.25 ? "before" : f > 0.75 ? "after" : "into";
  return f < 0.5 ? "before" : "after";
}

/** 這個座標底下的放置點（資料夾列、路徑按鈕、刪除區）/ The drop point under a coordinate (folder bar, breadcrumb, trash). */
function dropAtPoint(x, y) {
  const hit = document.elementFromPoint(x, y);
  if (!hit) return null;
  if (hit.closest("#libTrash")) return { trash: true };
  const d = hit.closest("[data-drop]");
  if (!d) return null;
  return { id: d.dataset.drop, kind: d.dataset.kind || "folder", zone: d.classList.contains("lt-row") ? zoneOf(d, y) : "into" };
}

function dropAt(evt) {
  const e = evt.originalEvent;
  const p = e && ((e.changedTouches && e.changedTouches[0]) || e);
  return p && p.clientX != null ? dropAtPoint(p.clientX, p.clientY) : null;
}

/** 在樹裡找一個節點的上層與它在裡面的位置 / Find a node's parent and its index in the tree. */
function locate(node, id) {
  const kids = node.children || [];
  for (let i = 0; i < kids.length; i++) {
    if (kids[i].id === id) return { parent: node, index: i };
    const f = locate(kids[i], id);
    if (f) return f;
  }
  return null;
}

/** 把這些項目搬到放置點的訊息：中間 = 放進資料夾，上緣／下緣 = 放進那一列的上層、插在它前面／後面（回傳 null = 不用做）
    The message that moves these items to a drop point: middle = into the folder, top / bottom edge = into that row's parent, right before / after it (null = nothing to do). */
function moveMsg(ids, drop) {
  if (drop.kind === "folder" && drop.zone === "into") return ids.includes(drop.id) ? null : { type: "lib_move", ids, to: drop.id };
  const root = getTree(), at = root && locate(root, drop.id);
  if (!at) return null;
  const sibs = (at.parent.children || []).filter((c) => !ids.includes(c.id));
  const i = sibs.findIndex((c) => c.id === drop.id);
  if (i < 0) return null;                                     // 放在被拖的自己身上 / dropped on one of the dragged items
  return { type: "lib_move", ids, to: at.parent.id, index: i + (drop.zone === "after" ? 1 : 0) };
}

/** 拖曳中：標出指標底下可以放的地方（資料夾列會依位置顯示放進去／插在上面／插在下面）
    While dragging: highlight the drop point under the pointer (a folder row shows inside / before / after). */
function over(e) {
  if (!box.classList.contains("lib-drag")) return;
  const t = e.target.closest && e.target.closest("[data-drop], #libTrash");
  const zone = t && t.classList.contains("lt-row") ? zoneOf(t, e.clientY) : "into";
  box.querySelectorAll(".drop-over, .drop-before, .drop-after").forEach((n) => {
    if (n !== t) n.classList.remove("drop-over", "drop-before", "drop-after");
  });
  if (!t) return;
  t.classList.toggle("drop-over", zone === "into");
  t.classList.toggle("drop-before", zone === "before");
  t.classList.toggle("drop-after", zone === "after");
}
box.addEventListener("pointermove", (e) => { lastPt = e; over(e); });

const start = () => box.classList.add("lib-drag");
function finish() {
  box.classList.remove("lib-drag");
  box.querySelectorAll(".drop-over, .drop-before, .drop-after").forEach((n) => n.classList.remove("drop-over", "drop-before", "drop-after"));
  endedAt = performance.now();
}

/** 放掉上一次畫的拖曳 / Release the previous drag setup. */
export function stopDrag() { if (inst) { inst.destroy(); inst = null; } }

/** 資料夾／歌單卡片：排序、搬進資料夾（拖到左邊的列，或直接放在另一張資料夾卡片的中央）、刪除。picked = 選取模式選了的 id
    Folder and playlist cards: reorder, move into a folder (drop on the bar on the left, or right on the middle of another folder card), delete. ``picked`` = ids chosen in select mode. */
export function dragCards(grid, folderId, picked) {
  stopDrag();
  // 指標移到資料夾卡片上時，先不讓卡片互換位置，停一下（0.3 秒）還在卡片中央就是"要放進去"；停了之後在邊緣才當作排序
  // When the pointer reaches a folder card the cards do not swap yet: resting 0.3 s on its middle means "put it inside"; after that, the edge counts as plain reordering.
  let cand = null, timer = 0;
  const unhot = () => { clearTimeout(timer); timer = 0; if (cand) { cand.classList.remove("drop-over"); cand = null; } };
  const inMiddle = (card, p) => {
    if (!p || p.clientX == null) return false;
    const r = card.getBoundingClientRect();
    return p.clientX > r.left + r.width * 0.2 && p.clientX < r.right - r.width * 0.2 && p.clientY > r.top + r.height * 0.2 && p.clientY < r.bottom - r.height * 0.2;
  };
  inst = new Sortable(grid, {
    ...options, draggable: ".lib-card", onStart: start,
    onMove: (evt, orig) => {
      const rel = evt.related;
      if (!rel || rel === evt.dragged || !rel.classList.contains("folder")) { unhot(); return undefined; }
      if (cand !== rel) {
        unhot(); cand = rel; rel.dwelled = false;
        timer = setTimeout(() => { if (cand === rel) { rel.dwelled = true; if (inMiddle(rel, lastPt)) rel.classList.add("drop-over"); } }, 300);
        return false;
      }
      if (!rel.dwelled) return false;
      if (inMiddle(rel, orig)) { rel.classList.add("drop-over"); return false; }
      rel.classList.remove("drop-over");
      return undefined;                                        // 停過了而且在邊緣：照一般排序 / rested already and at the edge: normal reordering
    },
    onEnd: (evt) => {
      const drop = dropAt(evt);                 // 要在收起刪除區之前量（收起後它就不吃指標事件了）/ measured before the trash hides (hidden, it ignores the pointer)
      const e = evt.originalEvent, p = e && ((e.changedTouches && e.changedTouches[0]) || e);
      const into = cand && inMiddle(cand, p) ? cand.dataset.id : null;
      unhot();
      finish();
      const id = evt.item.dataset.id;
      const ids = picked.has(id) && picked.size > 1 ? [...picked] : [id];      // 拖的是被選取的其中一張，就整批一起走 / dragging one of the picked cards takes them all
      const moved = evt.oldDraggableIndex !== evt.newDraggableIndex;
      let msg = null;
      if (drop && drop.trash) msg = { type: "lib_delete", ids };
      else if (drop) msg = drop.id !== folderId || drop.zone !== "into" ? moveMsg(ids, drop) : null;
      else if (into && !ids.includes(into)) msg = { type: "lib_move", ids, to: into };
      else if (moved) msg = { type: "lib_move", ids: [id], to: folderId, index: evt.newDraggableIndex };
      if (msg) send(msg);
      else if (moved) document.dispatchEvent(new CustomEvent("mb:lib-redraw"));   // 放在不能放的地方：還原畫面 / dropped somewhere that does not take it: redraw
    },
  });
}

/** 歌單裡的歌曲列：排序、搬到另一張歌單、從歌單移除。gate = { busy(), lock() }：列表還沒更新前不再動作（列是用編號算的）
    Song rows of a playlist: reorder, move to another playlist, remove from this one. ``gate`` = { busy(), lock() }: no more actions before the list refreshes (rows are addressed by number). */
export function dragSongs(list, playlistId, picked, gate) {
  stopDrag();
  inst = new Sortable(list, {
    ...options, draggable: ".lib-song", onStart: start,
    onEnd: (evt) => {
      const drop = dropAt(evt);                 // 要在收起刪除區之前量 / measured before the trash hides
      finish();
      const from = Number(evt.item.dataset.index);
      const idx = picked.has(String(from)) && picked.size > 1 ? [...picked].map(Number) : [from];
      const moved = evt.oldDraggableIndex !== evt.newDraggableIndex;
      let msg = null;
      if (drop && drop.trash) msg = { type: "lib_remove_songs", playlist: playlistId, indexes: idx };
      else if (drop && drop.kind === "playlist" && drop.id !== playlistId) msg = { type: "lib_song_move", playlist: playlistId, indexes: idx, to: drop.id };
      else if (!drop && moved) msg = { type: "lib_song_order", playlist: playlistId, from: evt.oldDraggableIndex, to: evt.newDraggableIndex };
      if (msg && !gate.busy()) { gate.lock(); send(msg); }
      else if (moved || msg) document.dispatchEvent(new CustomEvent("mb:lib-redraw"));    // 不能放（或太快）：把畫面還原 / not accepted (or too fast): redraw
    },
  });
}

/** 左邊資料夾列的拖曳：按住一列拖到另一列（放進去／插在上面／插在下面）或刪除區。只裝一次 / Dragging the rows of the folder bar: onto another row (inside / above / below) or the trash. Installed once. */
export function treeDrag(host) {
  let down = null, ghost = null;
  const cancel = () => {
    document.removeEventListener("pointermove", move); document.removeEventListener("pointerup", up); document.removeEventListener("keydown", key, true);
    if (ghost) { ghost.remove(); ghost = null; finish(); }
    host.querySelectorAll(".lt-lifted").forEach((n) => n.classList.remove("lt-lifted"));
    down = null;
  };
  const key = (e) => { if (e.key === "Escape") { e.stopPropagation(); cancel(); } };
  const move = (e) => {
    if (!down) return;
    if (!ghost) {
      if (Math.hypot(e.clientX - down.x, e.clientY - down.y) < 5) return;
      ghost = document.createElement("div");
      ghost.className = "lib-ghost"; ghost.textContent = down.row.querySelector(".lt-name").textContent;
      box.appendChild(ghost);
      down.row.classList.add("lt-lifted");
      start();
    }
    ghost.style.transform = `translate(${e.clientX + 12}px, ${e.clientY + 8}px)`;
  };
  const up = (e) => {
    const id = down && down.id, dragging = !!ghost;
    const drop = dragging ? dropAtPoint(e.clientX, e.clientY) : null;      // 要在收起刪除區之前量 / measured before the trash hides
    cancel();
    if (!dragging) return;
    endedAt = performance.now();
    if (!drop) return;
    if (drop.trash) send({ type: "lib_delete", ids: [id] });
    else if (drop.id !== id) { const m = moveMsg([id], drop); if (m) send(m); }
  };
  host.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || e.target.closest(".lt-caret")) return;
    const row = e.target.closest(".lt-row");
    if (!row || row.dataset.root) return;                      // 根（我的歌單）不能被搬走 / the root cannot be moved away
    down = { x: e.clientX, y: e.clientY, row, id: row.dataset.drop };
    document.addEventListener("pointermove", move); document.addEventListener("pointerup", up); document.addEventListener("keydown", key, true);
  });
}
