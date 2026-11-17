/* 進度條：點擊跳轉、拖曳預覽、鍵盤
   Seek bar: click to jump, drag to preview, keyboard */
import { send } from "./net.js";
import { render } from "./render.js";
import { S } from "./store.js";
import { el, fmt, setText } from "./util.js";

/* ------------------------------------------------------------ 進度條 / Seek bar */
/**
 * 可拖曳的進度條：點一下跳到該處，按住拖曳可預覽時間，放開才送出跳轉；也支援鍵盤左右鍵 ±5 秒
 * 沒有長度的曲目（直播）會停用，進度以 CSS 變數 --p（0~1）驅動
 *
 * A draggable seek bar: click to jump, press and drag to preview the time, the jump is sent on release;
 * the keyboard's Left/Right keys move it by +-5 s. Tracks without a duration (live streams) disable it.
 * The progress is driven by the CSS variable --p (0..1).
 */
export function makeSeekBar(c) {
  const seek = el("div", "seek");
  seek.setAttribute("role", "slider");
  seek.setAttribute("aria-label", T("seekAria"));
  seek.tabIndex = 0;
  const track = el("div", "seek-track");
  track.appendChild(el("div", "seek-fill"));
  const knob = el("div", "seek-knob");
  const tip = el("div", "seek-tip");
  seek.append(track, knob, tip);

  const dur = c.duration;
  if (!dur) { seek.classList.add("disabled"); return seek; }
  seek.setAttribute("aria-valuemin", "0");
  seek.setAttribute("aria-valuemax", String(dur));

  /** 指標位置 → 0~1 的比例 / Pointer position -> a 0..1 ratio. */
  const ratioOf = (e) => {
    const r = seek.getBoundingClientRect();
    return Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
  };
  const show = (ratio) => {            // 把進度、提示泡泡都移到 ratio 位置 / move both the progress and the tooltip to `ratio`
    seek.style.setProperty("--p", ratio);
    tip.style.left = `${ratio * 100}%`;
    tip.textContent = fmt(ratio * dur);
  };
  /** 真正送出跳轉（秒數會被限制在 0~長度-1）/ Actually send the seek (seconds clamped to 0..duration-1). */
  const commit = (seconds) => {
    seconds = Math.max(0, Math.min(dur - 1, Math.round(seconds)));
    send({ type: "seek", position: seconds });
    if (S.state && S.state.current) { S.state.current.position = seconds; S.recvAt = performance.now(); }   // 先在本地反映，不等伺服器 / reflect it locally first, without waiting for the server
  };

  seek.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    e.stopPropagation();               // 不要讓外層的卡片拖曳（SortableJS）接手 / keep the outer card drag (SortableJS) from taking over
    e.preventDefault();
    S.seeking = true;
    seek.classList.add("active");
    seek.setPointerCapture(e.pointerId);
    const ratio = ratioOf(e);
    show(ratio);
    if (S.nowRefs) setText(S.nowRefs.pos, fmt(ratio * dur));
  });
  seek.addEventListener("pointermove", (e) => {
    const ratio = ratioOf(e);
    if (S.seeking) { show(ratio); if (S.nowRefs) setText(S.nowRefs.pos, fmt(ratio * dur)); }
    else { tip.style.left = `${ratio * 100}%`; tip.textContent = fmt(ratio * dur); }   // 滑過時預覽目標時間 / preview the target time while hovering
  });
  seek.addEventListener("pointerup", (e) => {
    if (!S.seeking) return;
    S.seeking = false;
    seek.classList.remove("active");
    commit(ratioOf(e) * dur);
    if (S.deferred) { const s = S.deferred; S.deferred = null; render(s); }
  });
  seek.addEventListener("pointercancel", () => { S.seeking = false; seek.classList.remove("active"); });
  seek.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const c = S.state && S.state.current;
    const now = c ? c.position + (S.state.paused || c.loading ? 0 : (performance.now() - S.recvAt) / 1000) : 0;     // 暫停中位置不會動 / a paused position does not move
    commit(now + (e.key === "ArrowRight" ? 5 : -5));
  });
  return seek;
}

/**
 * 進度：以伺服器給的位置為基準，在本地推算，分頁隱藏時不做事
 * Progress: extrapolated locally from the position the server sent. Does nothing while the tab is hidden.
 */
export function tick() {
  if (document.hidden || S.seeking || !S.state || !S.state.current || !S.nowRefs) return;
  const c = S.state.current;
  const running = !S.state.paused && !c.loading;
  const pos = c.position + (running ? (performance.now() - S.recvAt) / 1000 : 0);
  const ratio = c.duration ? Math.min(1, pos / c.duration) : 0;
  setText(S.nowRefs.pos, fmt(pos));
  S.nowRefs.seek.style.setProperty("--p", ratio.toFixed(4));
}
setInterval(tick, 500);
document.addEventListener("visibilitychange", () => { if (!document.hidden) tick(); });
