/* 權限與限制：誰能控制、卡頓降低上限的公告
   Permissions and limits: who may control, the stutter cap notice */
import { input } from "./add.js";
import { sortNow, sortQueue } from "./dragdrop.js";
import { S } from "./store.js";
import { $, setText } from "./util.js";

/* ----------------------------------------------------- 誰能控制 / Who may control ----
   只有"人在語音頻道裡"的人能控制播放；其他人唯讀（伺服器端也會擋，這裡只是讓畫面誠實）

   In voice mode only people inside a voice channel may control playback; everyone else is read-only
   (the server enforces it too; this just keeps the UI honest). */
export const permBanner = $("#permBanner"), limitBanner = $("#limitBanner");

/** 卡頓偵測器降低了同時播放上限：把原因告訴大家 / The stutter detector lowered the simultaneous-stream cap: tell everyone why. */
export function syncLimit(s) {
  const note = s.limit && s.limit.notice;
  limitBanner.hidden = !note;
  if (note) setText(limitBanner, note);
}
/** 依權限切換唯讀樣式、提示列、拖曳功能與輸入框提示 / Apply the read-only style, banner, drag ability and input placeholder according to permissions. */
export function syncPerms(s) {
  const ro = !s.me.can_control;
  document.body.classList.toggle("readonly", ro);
  permBanner.hidden = !ro;
  if (ro) setText(permBanner, s.me.reason || T("readonly"));
  sortQueue.option("disabled", ro || !!S.targetChannel);
  sortNow.option("disabled", ro || !!S.targetChannel);
  input.placeholder = ro
    ? T("joinFirst")
    : S.targetChannel
      ? T("pasteTo", { name: (S.pendingTabs.find((t) => t.id === S.targetChannel) || {}).name || T("thisChannel") })
      : T("addPh");
}
