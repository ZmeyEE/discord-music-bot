/* 待播清單的視窗：只載入前面一段，往下捲再跟伺服器要更多；清單沒變時伺服器不會重送，這裡沿用手上那份
   （伺服器那一半在 musicbot/dashboard/queuewindow.py，數字在 musicbot/params.py 的 QUEUE_PAGE／QUEUE_VIEW）
   The queue window: only the first part is loaded and scrolling asks the server for more. When the list is unchanged the
   server doesn't send it again and the copy we hold is kept.
   (The server half is musicbot/dashboard/queuewindow.py, the numbers are QUEUE_PAGE / QUEUE_VIEW in musicbot/params.py.) */
import { queueEl, queueMoreEl } from "./dom.js";
import { send } from "./net.js";
import { S } from "./store.js";
import { setText } from "./util.js";
import { lastVisibleRow } from "./virtuallist.js";

const AHEAD_ROWS = 8;     // 看得到的最後一列離已載入的清單尾端不到幾列時，就去要下一批 / ask for the next batch when the last visible row is within this many rows of the end of what is loaded
const RETRY_MS = 3000;    // 要了之後沒等到，隔這麼久再要一次（正常情況是收到才會再要）/ if the answer never comes, ask again after this long (normally the next request waits for the answer)
let asked = 0, askedAt = 0;   // 上次要求的首數與時間 / what we last asked for, and when

/**
 * 伺服器沒帶 queue = 清單和上次一樣：把手上那份接回這份快照（render 一開始就會呼叫）
 * No `queue` from the server = the list is what we already have: put our copy back into this snapshot (render calls this first).
 */
export function keepQueue(s) {
  if (s.queue === undefined) s.queue = (S.state && S.state.queue) || [];
  return s;
}

/** 一連上就告訴伺服器"我懂沒變就不送"，並要回斷線前已經載入的張數 / On connect: tell the server we understand "unchanged, not sent" and ask for as many cards as we had before the disconnect. */
export function announceWindow() {
  send({ type: "queue_window", limit: S.state && S.state.queue ? S.state.queue.length : undefined });
}

/** 還能再載入嗎（還沒到總數，也還沒到一個瀏覽器的上限）/ Can more be loaded (below the total and below one browser's limit)? */
function canLoadMore(s) {
  const total = s.queue_total ?? s.queue.length;
  return !!s.queue_window && s.queue.length < Math.min(total, s.queue_window.max);
}

/** 捲到接近底部就要下一批 / Ask for the next batch when the view gets close to the bottom. */
function maybeLoadMore() {
  const s = S.state;
  if (!s || !s.queue || S.targetChannel || !canLoadMore(s)) return;
  if (s.queue.length - lastVisibleRow() > AHEAD_ROWS) return;
  if (asked > s.queue.length && performance.now() - askedAt < RETRY_MS) return;   // 上一批還沒到 / the last batch has not arrived yet
  // 每次要的量 = 目前已載入的量（至少一頁）：快速往下捲時 100、200、400... 很快就到底，慢慢捲則不會多要
  // Ask for as many again as are loaded (at least a page): fast scrolling goes 100, 200, 400... and reaches the end quickly.
  asked = Math.min(s.queue_window.max, s.queue.length + Math.max(s.queue_window.page, s.queue.length));
  askedAt = performance.now();
  send({ type: "queue_window", limit: asked });
}
queueEl.addEventListener("scroll", maybeLoadMore, { passive: true });
window.addEventListener("scroll", maybeLoadMore, { passive: true });

/**
 * 清單下方那一行字：還能載入就提示往下捲，到上限了就說後面還有幾首
 * The line under the list: a "scroll for more" hint while more can load, or how many songs follow once the limit is reached.
 * @param {object} v 目前分頁的畫面資料 / the view of the current tab
 */
export function syncQueueMore(v) {
  const shown = v.queue.length, total = v.queue_total ?? shown;
  queueMoreEl.hidden = total <= shown;
  if (queueMoreEl.hidden) return;
  setText(queueMoreEl, canLoadMore(v) ? T("queueScroll", { shown, total }) : T("queueMore", { shown, more: total - shown }));
}
