/* ==========================================================================
   常用節點只查一次 / the frequently used nodes, looked up only once
   ========================================================================== */
import { $ } from "./util.js";

export const queueEl = $("#queue"), nowDrop = $("#nowDrop"), trashCol = $("#trashCol");
export const queuePanel = document.querySelector(".col-queue");
export const guildNameEl = $("#guildName"), countEl = $("#queueCount"), queueMoreEl = $("#queueMore");
export const loopBtns = [...document.querySelectorAll("#loopBtns button")];
export const qualityBtns = [...document.querySelectorAll("#qualityBtns button")];
