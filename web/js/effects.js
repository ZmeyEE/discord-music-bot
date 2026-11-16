/* 撕裂特效：卡片被刪除時撕成兩半
   Tear-away effect: a deleted card tears in two */
import { $, REDUCED_MOTION, el } from "./util.js";

/* ----------------------------------------------------- 撕裂消失特效 / Tear-away effect */
/**
 * 把元素複製成左右兩片，沿著鋸齒狀的撕裂線裁開，
 * 兩片各自旋轉、飄開並淡出，最後移除，只用 transform / opacity，全程在合成階段處理
 *
 * Clone the element into a left and a right piece, cut along a jagged tear line; each piece rotates,
 * drifts away, fades and is finally removed. Only transform / opacity are animated, so it all runs
 * on the compositor.
 *
 * @param {Element} node            要撕掉的元素 / the element to tear
 * @param {number} delay            動畫延遲（毫秒）/ animation delay in ms
 * @param {DOMRect|null} rectOverride 指定位置（拖曳中元素已不在原處時用）/ explicit rectangle (used when the node is no longer where it was)
 */
export function tearAway(node, delay = 0, rectOverride = null) {
  if (!node || (!rectOverride && !node.isConnected)) return;
  // 這是一次性的短暫回饋，所以即使系統設為"減少動態效果"也會播放，只是幅度與時間減半
  // This is brief one-off feedback, so it plays even with "reduce motion" on, just at half the distance and duration.
  const k = REDUCED_MOTION ? 0.5 : 1;
  const r = rectOverride || node.getBoundingClientRect();
  if (r.width < 8 || r.height < 8) return;

  // 鋸齒撕裂線：從上到下，x 在中間附近隨機抖動
  // Jagged tear line: top to bottom, with x jittering randomly around the middle.
  const cx = 38 + Math.random() * 24;
  const steps = 14;
  const edge = [];
  for (let i = 0; i <= steps; i++) {
    const jag = (i % 2 ? 3.2 : -3.2) + (Math.random() - .5) * 4;
    edge.push([Math.min(92, Math.max(8, cx + jag)), (i / steps) * 100]);
  }
  const poly = (pts) => "polygon(" + pts.map(([x, y]) => `${x.toFixed(1)}% ${y.toFixed(1)}%`).join(", ") + ")";
  const pieces = [
    { clip: poly([[0, 0], ...edge, [0, 100]]), origin: "0% 100%", to: { x: -34 * k, y: 14 * k, rot: -9 * k } },
    { clip: poly([[100, 0], ...edge, [100, 100]]), origin: "100% 100%", to: { x: 34 * k, y: 6 * k, rot: 8 * k } },
  ];
  for (const p of pieces) {
    const wrap = el("div", "tear-piece");
    Object.assign(wrap.style, {
      left: `${r.left}px`, top: `${r.top}px`, width: `${r.width}px`, height: `${r.height}px`, transformOrigin: p.origin,
    });
    const clone = node.cloneNode(true);
    clone.classList.remove("sortable-fallback", "ghost");
    clone.removeAttribute("style");   // 拖曳中的浮動複本帶有 position:fixed 等行內樣式，要清掉 / the floating drag copy carries inline styles such as position:fixed; strip them
    clone.style.clipPath = p.clip;
    clone.style.webkitClipPath = p.clip;
    wrap.appendChild(clone);
    document.body.appendChild(wrap);
    wrap.animate(
      [
        { transform: "translate(0,0) rotate(0deg)", opacity: 1 },
        { transform: `translate(${p.to.x * .35}px, ${p.to.y * .2}px) rotate(${p.to.rot * .4}deg)`, opacity: .95, offset: .3 },
        { transform: `translate(${p.to.x}px, ${p.to.y + 26 * k}px) rotate(${p.to.rot}deg)`, opacity: 0 },
      ],
      { duration: 760 * (REDUCED_MOTION ? 0.75 : 1), delay, easing: "cubic-bezier(.25,.7,.3,1)", fill: "both" },
    ).onfinish = () => wrap.remove();
  }
}
