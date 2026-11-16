/* 渲染：把伺服器快照畫到畫面上（所有畫面更新的入口），與驗證畫面
   Rendering: draw a server snapshot (the single entry for screen updates), and the verify gate */
import { syncBili } from "./bili.js";
import { syncQueue } from "./cards.js";
import { countEl, guildNameEl, loopBtns, qualityBtns, queueMoreEl, queuePanel } from "./dom.js";
import { syncNow } from "./now.js";
import { permBanner, syncLimit, syncPerms } from "./perms.js";
import { tick } from "./seek.js";
import { S } from "./store.js";
import { playersBar, syncPlayers } from "./tabs.js";
import { $, PERF, setStatus, setText } from "./util.js";

/* ------------------------------------------------ 請用專屬連結進來（驗證模式）/ Please use your personal link (verify mode) ---- */
export const verifyGate = $("#verifyGate");
let verifyOn = false;

/** 顯示"請用專屬連結進來"畫面，隱藏看板 / Show the "use your personal link" screen and hide the dashboard. */
export function showVerify() {
  verifyOn = true;
  $("#board").hidden = true; document.querySelector(".topbar").hidden = true;
  playersBar.hidden = true; permBanner.hidden = true; limitBanner.hidden = true;
  verifyGate.hidden = false;
}
/** 驗證通過後恢復看板 / Restore the dashboard once verified. */
export function hideVerify() {
  verifyOn = false;
  verifyGate.hidden = true;
  $("#board").hidden = false; document.querySelector(".topbar").hidden = false;
}

/**
 * 正在看空分頁時，畫面上是"那個頻道自己的空狀態"，不是別的頻道的內容
 * When an empty tab is being viewed, the screen shows "that channel's own empty state", never another channel's content.
 */
export function viewOf(s) {
  if (!S.targetChannel) return s;
  const ch = s.channels.find((c) => c.id === S.targetChannel);
  return { ...s, current: null, queue: [], paused: false, loop: "off", connected: false, channel: ch ? ch.name : "", emptyTab: true };
}
/** 切換分頁後立刻重畫（不等伺服器回應，也不重置進度基準）/ Re-render at once after switching tabs (no server round-trip, and the progress baseline isn't reset). */
export function refresh() { if (S.state) render(S.state, true); }

/**
 * 把伺服器快照畫到畫面上（所有畫面更新的入口）
 * Draw a server snapshot on screen (the single entry point for every screen update).
 * @param {object} s      伺服器快照 / the server snapshot
 * @param {boolean} again 是 refresh() 觸發的重畫（不更新 recvAt）/ true when triggered by refresh() (recvAt is not updated)
 */
export function render(s, again = false) {
  S.state = s;
  if (!again) S.recvAt = performance.now();
  if (s.me && s.me.pending) { showVerify(); return; }   // 還沒驗證：只顯示驗證畫面 / not verified yet: show only the verify screen
  if (verifyOn) hideVerify();
  if (S.dragging || S.seeking) { S.deferred = s; return; }   // 拖曳中先不畫，放開後再套用 / don't draw during a drag; apply after release
  const t0 = PERF ? performance.now() : 0;
  document.body.classList.remove("offline");            // 收到狀態 = 播放端在線（syncPerms 會依權限決定提示列要不要顯示）/ receiving state = the worker is online (syncPerms decides whether the banner shows)

  syncPlayers(s);                      // 先整理分頁（頻道開始播放後，空分頁會變成正式分頁），再依目前分頁畫內容 / tabs first (an empty tab becomes a real one once its channel starts playing), then draw the current tab
  const v = viewOf(s);
  document.body.classList.toggle("empty-tab", !!v.emptyTab);

  setText(guildNameEl, s.guild.name);
  const cur = v.current;
  const title = (cur ? T("tabTitlePlaying", { title: cur.title }) : "") + T("title");
  if (document.title !== title) document.title = title;
  setStatus(
    v.emptyTab
      ? T("emptyTabStatus", { channel: v.channel })
      : v.connected
        ? T("connectedTo", { channel: v.channel }) + (cur && cur.bitrate ? ` · Opus ${cur.bitrate} kbps` : "")
        : T("notInVoice"),
    v.connected,
  );
  for (const b of loopBtns) b.setAttribute("aria-checked", String(b.dataset.loop === v.loop));
  for (const b of qualityBtns) b.setAttribute("aria-checked", String(Number(b.dataset.q) === s.quality.kbps));

  syncQueue(v.queue);
  const total = v.queue_total ?? v.queue.length;   // 看板最多畫前 1000 張，總數另外給 / the board draws at most the first 1000 cards, the total comes separately
  setText(countEl, String(total));
  queueMoreEl.hidden = total <= v.queue.length;
  if (!queueMoreEl.hidden) setText(queueMoreEl, T("queueMore", { shown: v.queue.length, more: total - v.queue.length }));
  queuePanel.classList.toggle("is-empty", total === 0);
  syncNow(v);
  syncPerms(s);
  syncLimit(s);
  syncBili(s);
  tick();

  if (PERF) {
    const ms = performance.now() - t0;
    (window.__renderMs = window.__renderMs || []).push(+ms.toFixed(2));
    console.log(`[perf] render ${ms.toFixed(2)}ms（待播 ${s.queue.length} 首）`);
  }
}
