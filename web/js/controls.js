/* 其他控制項：音質、循環、隨機、清空
   Other controls: quality, loop, shuffle, clear */
import { loopBtns, qualityBtns, queueEl } from "./dom.js";
import { tearAway } from "./effects.js";
import { send } from "./net.js";
import { S } from "./store.js";
import { $ } from "./util.js";

/* ------------------------------------------------------ 其他控制項 / Other controls */
loopBtns.forEach((b) => b.addEventListener("click", () => send({ type: "loop", mode: b.dataset.loop })));
qualityBtns.forEach((b) => b.addEventListener("click", () => {
  if (S.state && S.state.quality.kbps === Number(b.dataset.q)) return;   // 已經是這個音質 / already this quality
  send({ type: "quality", kbps: Number(b.dataset.q) });
}));

$("#btnShuffle").addEventListener("click", () => send({ type: "shuffle" }));

// 清空：第一次按先"上膛"，3 秒內再按一次才真的清空（取代瀏覽器內建的 confirm 對話框）
// Clear: the first press only "arms" the button; a second press within 3 s really clears (replaces the
// browser's built-in confirm dialog).
export const clearBtn = $("#btnClear");
let armedTimer;
clearBtn.addEventListener("click", () => {
  if (!S.state || !S.state.queue.length) return;
  if (!clearBtn.classList.contains("armed")) {
    clearBtn.classList.add("armed");
    armedTimer = setTimeout(() => clearBtn.classList.remove("armed"), 3000);
    return;
  }
  clearTimeout(armedTimer);
  clearBtn.classList.remove("armed");
  queueEl.querySelectorAll(".card").forEach((c, i) => { if (i < 12) tearAway(c, i * 70); });   // 最多演 12 張，避免長清單卡住 / animate at most 12 cards so a long list doesn't stall
  send({ type: "clear" });
});
