/* 拖曳排序、拖到刪除區、拖到正在播放
   Drag and drop: reorder, drag to the trash, drag to now playing */
import { nowDrop, queueEl, trashCol } from "./dom.js";
import { tearAway } from "./effects.js";
import { send } from "./net.js";
import { render } from "./render.js";
import { S } from "./store.js";
import { $ } from "./util.js";

/* ------------------------------------------------------------ 拖曳 / Drag & drop */
// SortableJS 的共用設定 / options shared by every Sortable instance
export const common = {
  animation: 150, ghostClass: "ghost", forceFallback: true, fallbackOnBody: true, fallbackTolerance: 3,
  delay: 80, delayOnTouchOnly: true,
  // 明確告訴 SortableJS 版面是直的：它就不必在每次移動時用 getComputedStyle 去猜方向（會強制重算樣式）
  // Tell SortableJS the layout is vertical, so it doesn't guess the direction with getComputedStyle on
  // every move (which forces a style recalculation).
  direction: "vertical",
};

// 撕裂特效需要知道"使用者放開手時卡片在哪"，SortableJS 在 onAdd 時已把浮動卡片移除，
// 所以自己記錄指標位置：開始拖曳時記下抓取點與卡片大小，拖曳中只記指標座標（不讀版面、不用 rAF）
// The tear effect needs to know where the card was when the user let go. SortableJS has already removed
// the floating card by onAdd, so we track the pointer ourselves: remember the grab point and card size
// when the drag starts, and only record pointer coordinates during the drag (no layout reads, no rAF).
let downPt = null, lastPt = null, grab = null, dragSize = null, dragClone = null;
document.addEventListener("pointerdown", (e) => { downPt = { x: e.clientX, y: e.clientY }; }, true);
document.addEventListener("pointermove", (e) => { if (S.dragging) lastPt = { x: e.clientX, y: e.clientY }; }, { passive: true });
/** 放開手時，浮動卡片大約所在的矩形 / The rectangle where the floating card roughly was at release. */
export const ghostRect = () => (lastPt && grab && dragSize
  ? { left: lastPt.x - grab.x, top: lastPt.y - grab.y, width: dragSize.w, height: dragSize.h }
  : null);

/** 開始拖曳：暫停重畫、記下抓取點與卡片大小 / Drag started: pause re-rendering and remember the grab point and card size. */
export const startDrag = (evt) => {
  S.dragging = true;
  document.body.classList.add("dragging");
  const r = evt.item.getBoundingClientRect();
  dragSize = { w: r.width, h: r.height };
  grab = downPt ? { x: downPt.x - r.left, y: downPt.y - r.top } : { x: r.width / 2, y: r.height / 2 };
  lastPt = downPt;
  dragClone = evt.item.cloneNode(true);
};
/** 結束拖曳：清理狀態並套用拖曳期間累積的最新快照 / Drag ended: clean up and apply the newest snapshot gathered during the drag. */
export const endDrag = () => {
  S.dragging = false;
  dragClone = null; grab = null; dragSize = null; lastPt = null;
  document.body.classList.remove("dragging");
  trashCol.classList.remove("over");
  S.handled.clear();
  if (S.deferred) { const s = S.deferred; S.deferred = null; render(s); }
};

/** 放開時滑鼠／手指是否在刪除區上（備援：即使 SortableJS 沒觸發 onAdd 也能刪除）/ Was the mouse/finger over the trash column at release? (a fallback so deletion works even if SortableJS didn't fire onAdd) */
export function releasedOverTrash(evt) {
  const e = evt.originalEvent;
  if (!e) return false;
  const p = (e.changedTouches && e.changedTouches[0]) || e;
  if (p.clientX == null) return false;
  const r = trashCol.getBoundingClientRect();
  return p.clientX >= r.left && p.clientX <= r.right && p.clientY >= r.top && p.clientY <= r.bottom;
}

/** 刪除一張被拖到刪除區的卡片：播撕裂特效並通知伺服器 / Delete a card dropped on the trash: play the tear effect and tell the server. */
export function deleteItem(item) {
  const key = item.dataset.id || "current";
  if (S.handled.has(key)) return;
  S.handled.add(key);
  const rect = ghostRect();
  if (dragClone && rect) tearAway(dragClone, 0, rect);   // 在放開手的地方撕開 / tear it where the hand let go
  else tearAway(item);
  if (item.dataset.current === "1") send({ type: "remove_current" });
  else send({ type: "remove", id: item.dataset.id });
  item.remove();
}

// 待播清單：可排序，也可拖出去（刪除區／正在播放）
// The queue: sortable, and cards can be dragged out of it (to the trash / to "now playing").
export const sortQueue = new Sortable(queueEl, {
  ...common,
  group: { name: "cards", pull: true, put: false },
  onStart: startDrag,
  onEnd: (evt) => {
    if (evt.to === evt.from && evt.oldIndex !== evt.newIndex) {
      send({ type: "move", id: evt.item.dataset.id, index: evt.newIndex });
    } else if (evt.to === evt.from && releasedOverTrash(evt)) {
      deleteItem(evt.item);
    }
    endDrag();
  },
});

// 刪除區（整個右側欄位）：放進去就刪
// Trash zone (the whole right-hand column): dropping a card here deletes it.
new Sortable($("#trash"), {
  ...common,
  group: { name: "cards", pull: false, put: true },
  onAdd: (evt) => deleteItem(evt.item),
});
trashCol.addEventListener("pointerenter", () => S.dragging && trashCol.classList.add("over"));
trashCol.addEventListener("pointerleave", () => trashCol.classList.remove("over"));

// 正在播放：放進來 = 立即播放；"正在播放"卡片本身也能拖去刪除區（= 跳過並移除）
// Now playing: dropping a card here = play it now; the "now playing" card itself can also be dragged to the trash (= skip and remove).
export const sortNow = new Sortable(nowDrop, {
  ...common,
  draggable: ".now-card",
  filter: ".seek, .ctrl",        // 進度條與控制按鈕上按下去，不要變成拖曳卡片 / pressing on the seek bar or controls must not start a card drag
  preventOnFilter: false,
  sort: false,
  group: { name: "cards", pull: true, put: true },
  onStart: startDrag,
  onAdd: (evt) => {
    const id = evt.item.dataset.id;
    evt.item.remove();
    send({ type: "play_now", id });
  },
  onEnd: (evt) => {
    if (evt.to === evt.from && releasedOverTrash(evt)) deleteItem(evt.item);
    endDrag();
  },
});
