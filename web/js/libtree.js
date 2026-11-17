/* 我的歌單：左邊的資料夾列（像檔案總管）。點一下就跳過去，也是拖曳的放置點
   My library: the folder bar on the left (like a file explorer). A click jumps there, and every row is a drop target for dragging
   只畫展開的資料夾，所以歌單很多時也不會有很多節點
   (only expanded folders are drawn, so even a big library stays a small DOM) */
import { justDragged } from "./libdrag.js";
import { el, icon } from "./util.js";

const open = new Set(["root"]);          // 展開中的資料夾 id / ids of expanded folders
let seen = "";                           // 上一次畫的位置；位置沒變（例如只是按了收合）就不要再自動展開 / where we were last time; unchanged (e.g. just a collapse click) must not re-expand

/** 目前所在位置的資料夾一路都展開 / Expand every folder on the way to where we are. */
function expandPath(path) { path.forEach((id) => open.add(id)); }

/** 畫出整列。active = 現在看的資料夾或歌單 id；go(id) = 點了某一列 / Draw the bar. ``active`` is the folder or playlist being viewed; ``go(id)`` is called on a click. */
export function drawTree(host, tree, path, active, rootLabel, go) {
  host.replaceChildren();
  if (!tree) return;
  const here = `${path.join("/")}|${active}`;
  if (here !== seen) { seen = here; expandPath(path); }          // 走到新位置才把一路上的資料夾展開 / expand the way only when we moved
  const row = (node, depth) => {
    const isFolder = node.type === "folder";
    const kids = isFolder ? node.children || [] : [];
    const r = el("div", "lt-row" + (node.id === active ? " active" : ""));
    r.dataset.drop = node.id; r.dataset.kind = node.type;
    if (node.id === tree.id) r.dataset.root = "1";
    r.style.paddingLeft = `${6 + depth * 14}px`;
    const caret = el("button", "lt-caret" + (kids.length ? "" : " none"));
    caret.type = "button"; caret.tabIndex = -1; caret.setAttribute("aria-label", "toggle");
    if (kids.length) {
      caret.textContent = open.has(node.id) ? "▾" : "▸";
      caret.addEventListener("click", (e) => { e.stopPropagation(); if (open.has(node.id)) open.delete(node.id); else open.add(node.id); drawTree(host, tree, path, active, rootLabel, go); });
    }
    const name = el("span", "lt-name", node.id === tree.id ? rootLabel : node.name);
    r.append(caret, icon(isFolder ? "folder" : "note", "i lt-i"), name);
    r.title = name.textContent;
    r.addEventListener("click", () => { if (!justDragged()) go(node.id); });
    host.appendChild(r);
    if (isFolder && open.has(node.id)) kids.forEach((k) => row(k, depth + 1));
  };
  row(tree, 0);
}
