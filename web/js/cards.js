/* 待播卡片：建立一張卡片、以 id 為 key 的差異更新
   Queue cards: build one card (which cards are drawn is decided by virtuallist.js) */
import { tearAway } from "./effects.js";
import { send } from "./net.js";
import { $, el, fmt, icon, setText, sized, sourceOf } from "./util.js";

/* ------------------------------------------------------------- 卡片 / Cards */

/** 縮圖方塊：載入失敗或沒有網址時顯示音符圖示 / A thumbnail box; shows a note icon when there is no URL or loading fails. */
export function thumb(url, cls, width) {
  const box = el("div", cls);
  const fallback = () => box.appendChild(icon("note"));
  if (url) {
    const img = new Image();
    img.referrerPolicy = "no-referrer";
    img.decoding = "async";        // 解碼不佔用主執行緒 / decode off the main thread
    img.loading = "lazy";
    img.draggable = false;
    img.alt = "";
    img.onerror = () => { img.remove(); fallback(); };
    img.src = sized(url, width);
    box.appendChild(img);
  } else {
    fallback();
  }
  return box;
}

/** 圖示按鈕（附無障礙標籤，點擊不會冒泡）/ An icon button with accessibility labels; the click does not bubble up. */
export function actionButton(label, iconName, cls, onClick) {
  const b = el("button", cls);
  b.type = "button";
  b.title = label;
  b.setAttribute("aria-label", label);
  b.appendChild(icon(iconName));
  b.addEventListener("click", (e) => { e.stopPropagation(); onClick(); });
  return b;
}

/** 卡片的"內容簽章"：簽章沒變就不需要重建這張卡片 / A card's "content signature": an unchanged signature means the card needn't be rebuilt. */
export const cardSig = (t) => [t.title, t.thumbnail, t.duration, t.uploader, t.requester, t.requester_avatar].join("\u0001");

/**
 * "點歌 [頭像] 暱稱"，沒有頭像（訪客、本地）或頭像載入失敗時，用暱稱的第一個字當圓形頭像
 * "Requested by [avatar] name". With no avatar (guest, local) or when it fails to load, the first
 * letter of the name is used as a round avatar.
 */
export function requesterNode(name, url) {
  const r = el("span", "req");
  r.title = T("requestedBy", { name });
  const initial = () => el("span", "req-av req-initial", [...name][0] || "?");
  let av;
  if (url) {
    av = new Image();
    av.className = "req-av"; av.alt = ""; av.width = av.height = 18;
    av.referrerPolicy = "no-referrer"; av.decoding = "async"; av.loading = "lazy";
    av.addEventListener("error", () => av.replaceWith(initial()), { once: true });
    av.src = url;
  } else av = initial();
  r.append(el("span", "req-label", T("requester")), av, el("span", "req-name", name));
  return r;
}

/** 在 meta 列加上"上傳者"與"點歌者"/ Add the uploader and the requester to a card's meta row. */
export function fillWho(meta, t) {
  if (t.uploader) meta.appendChild(el("span", "who", t.uploader));
  if (t.requester) meta.appendChild(requesterNode(t.requester, t.requester_avatar));
}

/** 建立待播清單裡的一張卡片 / Build one card of the queue list. */
export function makeCard(t, index) {
  const c = el("div", "card");
  c.dataset.id = t.id;
  c.dataset.sig = cardSig(t);

  const th = thumb(t.thumbnail, "thumb", 320);
  const idx = el("span", "idx", String(index + 1));
  th.appendChild(idx);
  const pick = el("span", "pick");     // 選取模式下的勾勾框 / the tick box of select mode
  pick.appendChild(icon("check"));
  th.appendChild(pick);
  c._idx = idx;
  c.appendChild(th);

  const info = el("div", "info");
  info.appendChild(el("div", "title", t.title));
  const meta = el("div", "meta");
  if (t.duration) meta.appendChild(el("span", "pill", fmt(t.duration)));
  const src = sourceOf(t.url);
  if (src) meta.appendChild(el("span", `pill ${src.cls}`, src.label));
  fillWho(meta, t);
  info.appendChild(meta);
  c.appendChild(info);

  const act = el("div", "actions");
  act.append(
    actionButton(T("addToList"), "bookmark", "", () => document.dispatchEvent(new CustomEvent("mb:add-to-list", { detail: { ids: [t.id] } }))),
    actionButton(T("playNow"), "play", "", () => send({ type: "play_now", id: t.id })),
    actionButton(T("remove"), "close", "x", () => { tearAway(c); send({ type: "remove", id: t.id }); }),
  );
  c.appendChild(act);
  return c;
}
