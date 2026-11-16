/* 小工具：建立元素、圖示、時間格式、提示訊息、辨識輸入
   Helpers: element and icon builders, time format, toast, input detection */

export const $ = (s) => document.querySelector(s);                       // 查詢單一節點的簡寫 / shorthand for querySelector
export const NS = "http://www.w3.org/2000/svg";                           // SVG 命名空間 / SVG namespace
export const REDUCED_MOTION = matchMedia("(prefers-reduced-motion: reduce)").matches;   // 使用者是否要求減少動態效果 / does the user ask for reduced motion?
export const PERF = new URLSearchParams(location.search).has("perf");     // 是否開啟效能紀錄 / performance logging switch

/* ---------------------------------------------------------- 小工具 / Helpers */

/** 建立元素並設定 class 與文字 / Create an element with an optional class and text. */
export const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
};

/** 建立引用 index.html 圖示庫的 <svg> / Build an <svg> that references the icon sprite in index.html. */
export const icon = (name, cls = "i") => {
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("class", cls);
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(NS, "use");
  use.setAttribute("href", `#i-${name}`);
  svg.appendChild(use);
  return svg;
};

/** 秒數 → m:ss 或 h:mm:ss / Seconds -> m:ss or h:mm:ss. */
export const fmt = (sec) => {
  if (sec == null || Number.isNaN(sec)) return "--:--";
  sec = Math.max(0, Math.floor(sec));
  const h = Math.floor(sec / 3600), mi = Math.floor((sec % 3600) / 60), s = sec % 60;
  return (h ? `${h}:${String(mi).padStart(2, "0")}` : `${mi}`) + `:${String(sec % 60).padStart(2, "0")}`;
};

/** 只在內容真的改變時才寫入，避免無謂的 DOM 變動與重繪 / Write only when the text really changed, avoiding needless DOM churn and repaints. */
export const setText = (node, text) => { if (node.textContent !== text) node.textContent = text; };

/**
 * Bilibili 圖床的縮圖原圖約 250KB（1920 級），但卡片只顯示 ~130px
 * 官方圖床支援尺寸參數，縮成 webp 後只剩 3~7KB，解碼成本差一個數量級
 *
 * Bilibili's CDN thumbnails are ~250 KB (1920 px class) while a card shows only ~130 px.
 * The CDN supports size parameters; as webp the image shrinks to 3-7 KB, an order of magnitude
 * cheaper to decode.
 */
export function sized(url, w) {
  if (!url || url.includes("@")) return url;
  try {
    if (/(^|\.)hdslb\.com$/.test(new URL(url).hostname)) return `${url}@${w}w_${Math.round((w * 9) / 16)}h_1c.webp`;
  } catch { /* 不是合法網址就原樣回傳 / not a valid URL: return it unchanged */ }
  return url;
}

let toastTimer;
/** 顯示一則短暫的提示訊息（約 4.8 秒）/ Show a short toast message (about 4.8 s). */
export function toast(text) {
  const t = $("#toast");
  t.textContent = text;
  t.hidden = false;
  t.style.animation = "none"; void t.offsetWidth; t.style.animation = "";   // 重新觸發 CSS 動畫 / restart the CSS animation
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), 4800);
}

/** 更新頂部的連線狀態文字與顏色（ok=綠／bad=紅）/ Update the connection status text and colour (ok = green, bad = red). */
export function setStatus(text, ok) {
  const s = $("#status");
  setText(s, text);
  const cls = "status " + (ok ? "ok" : "bad");
  if (s.className !== cls) s.className = cls;
}

/** 依網址判斷來源，用在卡片上的小標籤 / Work out the source site from a URL, for the small label on cards. */
export function sourceOf(url) {
  try {
    const h = new URL(url).hostname;
    if (/(^|\.)(bilibili\.com|b23\.tv)$/.test(h)) return { cls: "src-bili", label: "Bilibili" };
    if (/(^|\.)(youtube\.com|youtu\.be)$/.test(h)) return { cls: "src-yt", label: "YouTube" };
    if (/(^|\.)spotify\.com$/.test(h)) return { cls: "src-sp", label: "Spotify" };
    return { cls: "", label: h.replace(/^www\./, "") };
  } catch { return null; }
}

/**
 * 與伺服器端 normalize_query 相同的規則，只用來即時顯示"辨識為…"
 * Mirrors the server's normalize_query; used only to show the live "Detected as ..." hint.
 */
export function detect(raw) {
  const q = raw.trim();
  if (!q) return null;
  const u = q.match(/https?:\/\/[^\s<>"'「」『』【】（）]+/i);
  if (u) {
    try {
      const h = new URL(u[0]).hostname;
      if (/(^|\.)(bilibili\.com|b23\.tv)$/.test(h)) return { k: "bili", t: T("detectBili") };
      if (/(^|\.)(youtube\.com|youtu\.be)$/.test(h)) return { k: "yt", t: T("detectYt") };
      if (/(^|\.)spotify\.com$/.test(h)) return { k: "sp", t: T("detectSpotify") };
      return { k: "", t: T("detectUrlHost", { host: h.replace(/^www\./, "") }) };
    } catch { return { k: "", t: T("detectUrl") }; }
  }
  if (/(^|[^0-9A-Za-z])BV[0-9A-Za-z]{10}($|[^0-9A-Za-z])/.test(q)) return { k: "bili", t: T("detectBV") };
  if (/(^|[^0-9A-Za-z])av\d{4,}($|[^0-9A-Za-z])/i.test(q)) return { k: "bili", t: T("detectAv") };
  if (/^(yt|youtube)\s*[:：]/i.test(q)) return { k: "yt", t: T("detectYtSearch") };
  return { k: "bili", t: T("detectBiliSearch") };
}
