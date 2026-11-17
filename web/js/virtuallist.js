/* 待播清單的虛擬清單：幾千張卡片只畫看得到的那幾十張，其餘用上下兩塊空白撐出捲動高度
   （伺服器端的視窗在 musicbot/dashboard/queuewindow.py、往下捲載入更多在 queuewindow.js；這支只管"畫哪幾張"）
   Virtual queue list: with thousands of cards only the few dozen in view are drawn; two spacers hold the scroll height.
   (The server-side window is musicbot/dashboard/queuewindow.py and loading more on scroll is queuewindow.js; this file only decides which cards to draw.)

   為什麼要這樣：1000 張卡片就有兩萬多個節點，刪一張就要改幾百個序號、瀏覽器要重新排版整串；只畫看得到的，花費和清單長度無關
   Why: 1000 cards already mean 20k+ DOM nodes, and deleting one means rewriting hundreds of numbers and re-laying out the whole list.
   Drawing only what is visible makes the cost independent of the list length. */
import { makeCard, cardSig } from "./cards.js";
import { queueEl } from "./dom.js";
import { S } from "./store.js";
import { setText } from "./util.js";

const BUFFER = 14;      // 看得到的範圍上下各多畫幾張（拖曳時畫面不會露出空白，捲動也不會閃）/ extra cards drawn above and below the visible range (no blank edge while dragging, no flicker while scrolling)
const MARGIN = 4;       // 看得到的範圍離已畫範圍的邊還剩幾張時才重畫（避免每捲一點就動 DOM）/ redraw only when the visible range gets this close to the edge of what is drawn (not on every scroll tick)
const FALLBACK_ROW = 102;   // 還沒有任何卡片可以量時，一張卡片加間距的高度（92 + 10）/ card height plus gap before any card can be measured (92 + 10)
const NARROW = window.matchMedia("(max-width: 860px)");   // 窄螢幕：整頁一起捲，不是清單自己捲 / narrow screens: the whole page scrolls instead of the list

let list = [];              // 目前載入的整份清單（可能有幾千首）/ the whole loaded list (may be thousands)
let first = 0, last = 0;    // 現在畫出來的範圍 [first, last) / the range drawn right now
let rowH = FALLBACK_ROW;    // 一列的高度 = 卡片 + 間距 / one row = card + gap
let gap = 10;
const nodes = new Map();    // id -> 卡片元素（只留畫出來的）/ id -> card element (only the drawn ones)
const topSpace = Object.assign(document.createElement("div"), { className: "vspace" });
const bottomSpace = Object.assign(document.createElement("div"), { className: "vspace" });
let queued = false;

/** 目前畫到的第一張的位置（拖曳排序時要靠它換算成整份清單的位置）/ Position of the first drawn card (reordering by drag needs it to get the position in the whole list). */
export const firstDrawn = () => first;

/**
 * 看得到的範圍是第幾列到第幾列（小數）
 * 寬螢幕清單自己捲，窄螢幕整頁捲，所以"可見區"和"內容頂端"的算法不同
 * Which rows are in view (fractional). On wide screens the list scrolls itself, on narrow ones the page does,
 * so the visible area and the top of the content are worked out differently.
 */
function viewRows() {
  const r = queueEl.getBoundingClientRect();
  const own = !NARROW.matches;
  const top = own ? Math.max(0, r.top) : 0;
  const bottom = own ? Math.min(window.innerHeight, r.bottom) : window.innerHeight;
  const content = r.top - (own ? queueEl.scrollTop : 0) + 4;      // +4 = .cards 的上方留白 / the list's top padding
  return { from: (top - content) / rowH, to: (bottom - content) / rowH };
}

/** 捲到最底部附近時，看得到的最後一列的位置（往下載入更多要用）/ The last visible row; used to decide when to load more. */
export function lastVisibleRow() {
  return Math.min(list.length, Math.ceil(viewRows().to));
}

/** 量一張卡片加間距有多高（版面改變時會不一樣）/ Measure how tall a card plus its gap is (it changes with the layout). */
function measure() {
  const card = queueEl.querySelector(".card");
  if (!card) return;
  gap = parseFloat(getComputedStyle(queueEl).rowGap) || 10;
  rowH = card.offsetHeight + gap;
}

/** 把上下兩塊空白調成剛好撐出沒畫出來的那些列 / Size the two spacers so they stand in for the rows that are not drawn. */
function placeSpacers() {
  const hold = (el, rows) => {
    el.style.height = rows > 0 ? `${rows * rowH - gap}px` : "0";   // 減掉一個間距：空白本身和相鄰卡片之間已經有一個 / minus one gap: there is already one between the spacer and its neighbour
    el.hidden = rows <= 0;
  };
  hold(topSpace, first);
  hold(bottomSpace, list.length - last);
}

/** 畫出 [from, to) 這幾張，沿用已經有的卡片，其餘移除 / Draw rows [from, to): keep the cards already there, drop the rest. */
function draw(from, to) {
  first = from; last = to;
  const wanted = new Set();
  for (let i = from; i < to; i++) wanted.add(list[i].id);
  for (const [id, node] of nodes) {
    if (!wanted.has(id)) { node.remove(); nodes.delete(id); }
  }
  if (topSpace.parentNode !== queueEl) queueEl.prepend(topSpace);
  if (bottomSpace.parentNode !== queueEl) queueEl.append(bottomSpace);
  let cursor = topSpace.nextElementSibling;
  for (let i = from; i < to; i++) {
    const t = list[i];
    let node = nodes.get(t.id);
    if (!node) {
      node = makeCard(t, i);
      nodes.set(t.id, node);
    } else if (node.dataset.sig !== cardSig(t)) {            // 卡片內容變了（例如補到縮圖）：換一張新的 / content changed (e.g. a thumbnail arrived): swap in a new card
      const fresh = makeCard(t, i);
      node.replaceWith(fresh);
      if (node === cursor) cursor = fresh;
      node = fresh;
      nodes.set(t.id, node);
    }
    if (node._idx) setText(node._idx, String(i + 1));
    if (node === cursor) cursor = cursor.nextElementSibling;
    else queueEl.insertBefore(node, cursor);
  }
  measure();
  placeSpacers();
}

/** 依目前的捲動位置決定要畫哪幾張；還在已畫範圍裡就什麼都不做 / Decide which rows to draw from the scroll position; do nothing while the view is still well inside what is drawn. */
function layout(force = false) {
  queued = false;
  if (S.dragging) return;                                       // 拖曳中不能換節點 / never swap nodes during a drag
  if (!list.length) { if (first || last || nodes.size || force) draw(0, 0); return; }
  const { from, to } = viewRows();
  // 已畫範圍的上下邊都還有 MARGIN 列的餘裕（或已經是清單的頭／尾）就不用動 / both edges of the drawn range still have MARGIN rows to spare (or are the start / end of the list): nothing to do
  const covered = (first === 0 || from - MARGIN >= first) && (last === list.length || to + MARGIN <= last);
  if (!force && covered) return;
  draw(Math.max(0, Math.floor(from) - BUFFER), Math.min(list.length, Math.ceil(to) + BUFFER));
}

/** 捲動時排一次重畫（一個畫面最多一次）/ Schedule one layout per frame while scrolling. */
function schedule() {
  if (queued) return;
  queued = true;
  requestAnimationFrame(() => layout());
}

/**
 * 收到新的清單：換掉手上那份並重畫
 * The list changed: swap our copy and redraw.
 * @param {Array} next 整份已載入的清單 / the whole loaded list
 */
export function syncQueue(next) {
  list = next;
  if (!list.length) { layout(true); return; }
  const { from, to } = viewRows();
  if (Math.floor(from) >= list.length) { layout(true); return; }      // 清單一下子縮短，捲動位置已經在最後面之外：整個重排 / the list shrank below the scroll position: lay out again
  draw(Math.max(0, Math.floor(from) - BUFFER), Math.min(list.length, Math.ceil(to) + BUFFER));
}

queueEl.addEventListener("scroll", schedule, { passive: true });
window.addEventListener("scroll", schedule, { passive: true });
window.addEventListener("resize", () => { measure(); schedule(); });
NARROW.addEventListener("change", () => layout(true));
