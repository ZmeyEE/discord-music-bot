/* ==========================================================================
   音樂看板 — 前端進入點（原生 JS，ES 模組，無建置步驟）
   Music dashboard — front-end entry point (vanilla JS, ES modules, no build step)

   - 與機器人用 WebSocket 即時同步：伺服器每次狀態改變都會推送完整快照
     Stays in sync with the bot over a WebSocket: every state change pushes a full snapshot.
   - 渲染採"以 id 為 key 的差異更新"：只動有變的卡片，其餘 DOM（含已解碼的圖片）原封不動
     Rendering is a keyed diff (by track id): only changed cards are touched, the rest of the DOM is left alone.
   - 拖曳使用 SortableJS（web/vendor/Sortable.min.js，MIT）
     Drag & drop uses SortableJS (web/vendor/Sortable.min.js, MIT licence).
   - 網址加上 ?perf 可在主控台看到每次渲染的耗時
     Add ?perf to the URL to see each render's duration in the console.

   檔案地圖 / File map（web/js/）:
     最底層 lowest layer  util.js 小工具 · store.js 共用狀態 · dom.js 常用節點
     畫面零件 pieces      effects.js 撕裂特效 · cards.js 待播卡片 · now.js 正在播放 · seek.js 進度條
     功能 features        dragdrop.js 拖曳 · controls.js 其他控制 · add.js 加歌 · tabs.js 分頁 · perms.js 權限 · bili.js Bilibili 帳號
     清單視窗 window      queuewindow.js 只載入前面一段、往下捲再要、沒變就不重送 · virtuallist.js 只畫看得到的卡片
     我的歌單 library     library.js 視窗與卡片 · libsongs.js 歌曲列 · libdialogs.js 小視窗 · selection.js 待播清單的選取與加入歌單
     Spotify spotify.js 帳號連結 · libspotify.js 自己的 Spotify 歌單
     組合 assembly        render.js 把快照畫到畫面 · net.js WebSocket 連線 · picker.js 沒指定伺服器時的選單
   從下往上讀：先看底層，再看零件，最後看 render.js 怎麼把它們串起來
   Read from the bottom up: the lowest layer first, then the pieces, and finally how render.js ties them together.
   ========================================================================== */
import "./add.js";
import "./bili.js";
import "./controls.js";
import "./dragdrop.js";
import "./library.js";
import "./perms.js";
import "./render.js";
import "./selection.js";
import "./spotify.js";
import "./tabs.js";
import { connect } from "./net.js";
import { gid } from "./store.js";
import { initPicker } from "./picker.js";

if (gid) connect();      // 有指定伺服器：連線 / a server is named: connect
else initPicker();       // 沒指定：顯示選單 / none named: show the picker
