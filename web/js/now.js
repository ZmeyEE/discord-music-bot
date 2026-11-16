/* 正在播放：大卡片、暫停按鈕
   Now playing: the big card and the pause button */
import { actionButton, fillWho, thumb } from "./cards.js";
import { nowDrop } from "./dom.js";
import { send } from "./net.js";
import { makeSeekBar } from "./seek.js";
import { S } from "./store.js";
import { $, el, fmt, icon, sourceOf } from "./util.js";

let nowKey = null;            // "正在播放"卡片的內容簽章 / content signature of the "now playing" card

/** 依暫停狀態切換"暫停／繼續"按鈕的圖示 / Switch the pause/resume button's icon according to the paused state. */
export function setPauseButton(btn, paused) {
  const name = paused ? "play" : "pause";
  if (btn.dataset.icon === name) return;
  btn.dataset.icon = name;
  btn.replaceChildren(icon(name));
  btn.title = paused ? T("resume") : T("pause");
  btn.setAttribute("aria-label", btn.title);
}

/** 更新"正在播放"區塊（沒有歌時顯示空狀態）/ Update the "now playing" block (shows an idle state when nothing plays). */
export function syncNow(s) {
  const c = s.current;
  if (!c) {
    if (nowKey !== "idle") {
      const idle = el("div", "idle");
      idle.append(icon("note"), el("span", "", T("nothingPlaying")));
      nowDrop.replaceChildren(idle);
      nowKey = "idle"; S.nowRefs = null;
    }
    return;
  }
  const key = [c.id, c.title, c.thumbnail, c.duration, c.uploader, c.requester, c.requester_avatar, c.loading, c.quality, c.bitrate, c.direct].join("\u0001");
  const present = nowDrop.firstElementChild && nowDrop.firstElementChild.dataset.current === "1";   // 卡片還在畫面上嗎 / is the card still on screen?
  if (key !== nowKey || !present) {          // 換歌、載入完成補上音質、或卡片被拖走後沒換歌：才重建整張卡片 / rebuild only on a song change, when loading finished and quality arrived, or when the card was dragged away without a song change
    nowDrop.replaceChildren(makeNowCard(s));
    nowKey = key;
  }
  if (S.nowRefs) setPauseButton(S.nowRefs.pause, s.paused);   // 暫停／繼續只換按鈕圖示 / pause/resume only swaps the button icon
}

export function makeNowCard(s) {
  const c = s.current;
  const card = el("div", "now-card");
  card.dataset.current = "1";
  card.appendChild(thumb(c.thumbnail, "art", 640));
  card.appendChild(el("div", "title", c.title));

  const meta = el("div", "meta");
  const src = sourceOf(c.url);
  if (src) meta.appendChild(el("span", `pill ${src.cls}`, src.label));
  fillWho(meta, c);
  card.appendChild(meta);

  if (c.loading) card.appendChild(el("span", "chip loading", T("loading")));
  else if (c.quality) card.appendChild(el("span", "chip", c.direct ? T("sourceDirect", { quality: c.quality }) : T("sourceChip", { quality: c.quality, bitrate: c.bitrate })));

  const seek = makeSeekBar(c);
  card.appendChild(seek);

  const times = el("div", "times");
  const pos = el("span", "", "0:00");
  times.append(pos, el("span", "", c.duration ? fmt(c.duration) : "--:--"));
  card.appendChild(times);

  const ctrl = el("div", "ctrl");
  const pause = actionButton(T("pause"), "pause", "main", () => send({ type: "toggle_pause" }));
  pause.dataset.icon = "pause";
  ctrl.append(
    actionButton(T("next"), "next", "", () => send({ type: "skip" })),
    pause,
    actionButton(T("stopLeave"), "stop", "danger", () => send({ type: "stop" })),
  );
  card.appendChild(ctrl);

  S.nowRefs = { seek, pos, pause, duration: c.duration };
  return card;
}
