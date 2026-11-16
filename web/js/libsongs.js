/* 我的歌單：打開一張歌單時的歌曲列表（一次只拿 300 首，往下再要）
   My library: the song list of an opened playlist (300 songs at a time, more on demand) */
import { send } from "./net.js";
import { thumb } from "./cards.js";
import { el, fmt, icon } from "./util.js";

const state = { id: null, songs: [], total: 0, waiting: false, host: null, L: null };

/** 開始看某張歌單：清掉舊的並向伺服器要第一批 / Start viewing a playlist: forget the old songs and ask for the first batch. */
export function openSongs(node) {
  state.id = node.id; state.songs = []; state.total = node.count; state.waiting = true;
  send({ type: "lib_open", id: node.id, offset: 0 });
}

/** 離開歌單 / Leave the playlist. */
export function closeSongs() { state.id = null; state.songs = []; }

/** 重新載入目前這張歌單（移除歌之後用）/ Reload the current playlist (after removing songs). */
function reload() { if (state.id) openSongs({ id: state.id, count: state.total }); }

/** 畫歌曲列 / Draw the song rows. */
function draw(body, node, L, enter) {
  state.host = body; state.L = L;
  body.replaceChildren();
  if (!node) return;
  if (state.waiting && !state.songs.length) { body.appendChild(el("p", "lib-sub", "…")); return; }
  if (!state.songs.length) { body.appendChild(el("div", "lib-empty", T("libNoSongs"))); return; }
  const list = el("div", "lib-songs");
  state.songs.forEach((s, i) => list.appendChild(row(s, i)));
  body.appendChild(list);
  if (enter) enter(list);
  if (state.songs.length < state.total) {
    const more = el("button", "btn-ghost lib-more", T("libLoadMore", { n: state.total - state.songs.length }));
    more.type = "button";
    const ask = () => {
      if (state.waiting) return;
      state.waiting = true; more.disabled = true;
      send({ type: "lib_open", id: state.id, offset: state.songs.length });
    };
    more.addEventListener("click", ask);
    body.appendChild(more);
    new IntersectionObserver((es, ob) => { if (es.some((x) => x.isIntersecting)) { ob.disconnect(); ask(); } }, { root: body, rootMargin: "300px" }).observe(more);
  }
}

/** 一首歌一列 / One row per song. */
function row(s, i) {
  const L = state.L;
  const r = el("div", "lib-song");
  r.dataset.index = String(i);
  r.title = s.url;
  const t = el("div", "t");
  t.append(el("b", "", s.title || s.url), el("small", "", [s.duration ? fmt(s.duration) : "", s.uploader].filter(Boolean).join(" · ")));
  const x = el("button", "x"); x.type = "button"; x.title = T("libRemoveSong"); x.setAttribute("aria-label", T("libRemoveSong")); x.appendChild(icon("close"));
  x.addEventListener("click", (e) => { e.stopPropagation(); send({ type: "lib_remove_songs", playlist: state.id, indexes: [i] }); });
  r.append(thumb(s.thumbnail, "thumb", 160), t, x);
  const key = String(i);
  if (L.picked.has(key)) r.classList.add("selected");
  r.addEventListener("click", () => {
    if (!L.selecting) return;
    if (L.picked.has(key)) L.picked.delete(key); else L.picked.add(key);
    r.classList.toggle("selected", L.picked.has(key));
    document.dispatchEvent(new CustomEvent("mb:lib-bar"));
  });
  return r;
}

/** 伺服器回了一批歌 / A batch of songs arrived. */
function onSongs(data) {
  if (data.id !== state.id) return;
  state.waiting = false;
  state.total = data.total;
  if (data.offset === 0) state.songs = data.songs; else state.songs = state.songs.concat(data.songs);
  if (state.host) draw(state.host, { id: state.id }, state.L, null);
}

export const songsView = { draw, onSongs, reload };
