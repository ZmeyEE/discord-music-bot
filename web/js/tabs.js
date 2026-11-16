/* 多播放器分頁：每個頻道一個分頁
   Multi-player tabs: one tab per channel */
import { input } from "./add.js";
import { send } from "./net.js";
import { refresh } from "./render.js";
import { S } from "./store.js";
import { $, el, icon } from "./util.js";

/* ------------------------------------------------ 多播放器（分身）分頁 / Multi-player (clone) tabs ----
   同一個伺服器有多個播放器時（每個頻道一個），上方出現分頁，預設自動跟著"你所在的頻道"，點分頁可改看別的

   When a server has several players (one per channel), tabs appear on top. By default the view follows
   "the channel you are in"; click a tab to look at another one. */
export const playersBar = $("#playersBar");
let playersSig = "";     // 上一次畫分頁列時的簽章，沒變就不重畫 / signature of the last tab-bar render; unchanged = no re-render
let menuOpen = false;    // "＋ 加到頻道"選單是否展開 / is the "+ add to channel" menu open?

/**
 * 頻道有播放器了（空分頁變成正式分頁）或頻道不見了 → 把空分頁整理掉；回傳是否需要重畫
 * A channel now has a player (the empty tab becomes a real tab) or the channel vanished -> tidy up the
 * empty tabs; returns whether the view needs a re-render.
 */
export function reconcileTabs(s) {
  const byId = new Map(s.channels.map((c) => [c.id, c]));
  let viewChanged = false;
  S.pendingTabs = S.pendingTabs.filter((t) => {
    const ch = byId.get(t.id);
    if (!ch) { if (S.targetChannel === t.id) { S.targetChannel = null; viewChanged = true; } return false; }
    if (ch.pid) {                                   // 第一首歌已經加進去、機器人進頻道了：空分頁變成正式分頁 / the first song was added and the bot entered the channel: the empty tab becomes a real one
      if (S.targetChannel === t.id) { S.targetChannel = null; viewChanged = true; send({ type: "select", pid: ch.pid }); }
      return false;
    }
    t.name = ch.name;
    return true;
  });
  return viewChanged;
}

/** 在選單選了一個頻道：立刻開成一個獨立的空分頁 / A channel was picked in the menu: open it right away as an independent empty tab. */
export function openTab(id) {
  const ch = S.state.channels.find((c) => c.id === id);
  if (!ch) return;
  if (!S.pendingTabs.some((t) => t.id === id)) S.pendingTabs.push({ id, name: ch.name });
  S.targetChannel = id; menuOpen = false; playersSig = "";
  refresh();
  input.focus();
}
/** 關閉一個空分頁 / Close an empty tab. */
export function closeTab(id) {
  S.pendingTabs = S.pendingTabs.filter((t) => t.id !== id);
  if (S.targetChannel === id) S.targetChannel = null;
  playersSig = "";
  refresh();
}

/** 重畫分頁列（正式分頁、空分頁、"＋ 加到頻道"選單、使用中數量）/ Re-render the tab bar (real tabs, empty tabs, the "+ add to channel" menu, the in-use counter). */
export function syncPlayers(s) {
  // 只有"剛好一個播放器、也沒有分身"的單純情況才不需要這一列
  // The bar is only unnecessary in the simple case "exactly one player and no clones".
  const show = s.players.length !== 1 || s.clones.total > 1 || S.pendingTabs.length > 0;
  playersBar.hidden = !show;
  if (!show) { playersSig = ""; S.targetChannel = null; return; }
  reconcileTabs(s);

  const free = s.channels.filter((c) => !c.pid && !S.pendingTabs.some((t) => t.id === c.id));   // 還沒有播放器、也還沒開分頁的語音頻道 / voice channels with no player and no tab yet
  const canAdd = s.clones.idle > 0 && free.length > 0 && !(s.limit && s.limit.reached);       // 還有閒置的機器人、且沒被卡頓偵測器暫時擋住 / an idle bot exists and the stutter detector isn't blocking new channels
  const sig = JSON.stringify([s.selected, S.targetChannel, menuOpen, s.players.map((p) => [p.pid, p.name, p.paused, !!p.title]),
    S.pendingTabs.map((t) => [t.id, t.name]), s.clones, s.limit && [s.limit.max, s.limit.reached], canAdd && free.map((c) => [c.id, c.name, c.members])]);
  if (sig === playersSig) return;
  playersSig = sig;

  // 正式分頁（每個播放器一個）/ real tabs (one per player)
  const chips = s.players.map((p) => {
    const b = el("button", `player-chip ${p.title ? (p.paused ? "paused" : "playing") : ""}`);
    b.type = "button";
    b.setAttribute("role", "tab");
    b.setAttribute("aria-selected", String(p.pid === s.selected && !S.targetChannel));
    b.title = p.title ? `${p.bot}：${p.title}` : p.bot;
    b.append(el("span", "dot"), el("span", "label", p.name), el("small", "", p.bot));
    b.addEventListener("click", () => { S.targetChannel = null; playersSig = ""; send({ type: "select", pid: p.pid }); refresh(); });
    return b;
  });

  // 還沒開始播放的頻道分頁：自己獨立的一頁，在這裡加歌只會進這個頻道
  // Tabs of channels that haven't started playing: each one is its own page, and songs added here go to this channel only.
  const empties = S.pendingTabs.map((t) => {
    const wrap = el("span", "tab-wrap");
    const b = el("button", "player-chip fresh");
    b.type = "button";
    b.setAttribute("role", "tab");
    b.setAttribute("aria-selected", String(S.targetChannel === t.id));
    b.title = T("freshTabTip", { name: t.name });
    b.append(el("span", "dot"), el("span", "label", t.name), el("small", "", T("notPlayingYet")));
    b.addEventListener("click", () => { S.targetChannel = t.id; playersSig = ""; refresh(); input.focus(); });
    const x = el("button", "tab-close");
    x.type = "button"; x.title = T("closeTab"); x.setAttribute("aria-label", T("closeTabNamed", { name: t.name }));
    x.appendChild(icon("close"));
    x.addEventListener("click", (e) => { e.stopPropagation(); closeTab(t.id); });
    wrap.append(b, x);
    return wrap;
  });

  const nodes = [...chips, ...empties];
  if (canAdd) {
    // "＋ 加到頻道"按鈕與下拉選單 / the "+ add to channel" button and its dropdown
    const wrap = el("span", "chan-wrap");
    const add = el("button", "player-chip add", T("addToChannel"));
    add.type = "button";
    add.setAttribute("aria-haspopup", "menu");
    add.setAttribute("aria-expanded", String(menuOpen));
    add.title = T("addToChannelTip");
    add.addEventListener("click", (e) => { e.stopPropagation(); menuOpen = !menuOpen; playersSig = ""; syncPlayers(S.state); });
    wrap.appendChild(add);
    if (menuOpen) {
      const menu = el("div", "menu");
      menu.setAttribute("role", "menu");
      free.forEach((c) => {
        const it = el("button", "menu-item");
        it.type = "button";
        it.setAttribute("role", "menuitem");
        it.append(el("span", "", c.name), el("small", "", c.members ? T("members", { n: c.members }) : T("nobody")));
        it.addEventListener("click", (e) => { e.stopPropagation(); openTab(c.id); });
        menu.appendChild(it);
      });
      wrap.appendChild(menu);
    }
    nodes.push(wrap);
  }
  const info = el("span", "clones",
    s.players.length ? T("playersUsed", { used: s.clones.total - s.clones.idle, total: s.clones.total }) : T("pickChannelFirst"));
  info.title = s.limit && s.limit.reached && s.limit.max < s.limit.cap
    ? T("stutterCap", { n: s.limit.max })
    : s.clones.idle ? T("idleClones", { n: s.clones.idle }) : T("allBusy");
  nodes.push(info);
  playersBar.replaceChildren(...nodes);
}
document.addEventListener("click", () => { if (menuOpen) { menuOpen = false; playersSig = ""; if (S.state) syncPlayers(S.state); } });   // 點旁邊就收起選單 / a click elsewhere closes the menu
