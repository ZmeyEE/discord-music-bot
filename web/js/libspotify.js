/* 歌單視窗裡的 Spotify 歌單：只有連結了 Spotify 帳號才看得到，點一張就存進"我的歌單"
   Spotify playlists inside the library dialog: only visible once a Spotify account is linked; click one to save it into "My playlists" */
import { send } from "./net.js";
import { SP } from "./spotify.js";
import { el, icon } from "./util.js";

/** 向伺服器要自己的 Spotify 歌單 / Ask the server for the user's own Spotify playlists. */
export function loadSpotifyLists() {
  SP.playlists = null;
  send({ type: "sp_playlists" });
}

/**
 * 畫 Spotify 歌單卡片；點一張就匯入成我的歌單（放在目前的資料夾）
 * Draw the Spotify playlist cards; clicking one imports it as a library playlist (in the current folder).
 * @param {HTMLElement} body 要畫進哪裡 / where to draw
 * @param {string} parent    匯入到哪個資料夾 id / the folder id to import into
 */
export function drawSpotify(body, parent) {
  body.replaceChildren();
  body.appendChild(el("p", "lib-sub", T("spOnlyNote")));
  if (SP.playlists === null) { body.appendChild(el("p", "lib-sub", T("spListsLoading"))); return; }
  if (!SP.playlists.length) { body.appendChild(el("div", "lib-empty", T("spNone"))); return; }
  const grid = el("div", "lib-grid");
  for (const p of SP.playlists) {
    const card = el("div", "lib-card playlist sp-card");
    card.tabIndex = 0;
    const art = el("div", "lib-art");
    if (p.image) {
      const img = new Image(); img.src = p.image; img.alt = ""; img.referrerPolicy = "no-referrer"; img.loading = "lazy"; img.draggable = false;
      img.onerror = () => { img.remove(); art.appendChild(icon("note")); };
      art.appendChild(img);
    } else art.appendChild(icon("note"));
    const importIt = () => { send({ type: "sp_import", id: p.id, name: p.name, parent }); };
    card.append(art, el("div", "lib-name", p.name), el("div", "lib-sub", `${T("libSongs", { n: p.count })}${p.owner ? " · " + p.owner : ""}`), el("div", "sp-hint", T("spImport")));
    card.title = p.name;
    card.addEventListener("click", importIt);
    card.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); importIt(); } });
    grid.appendChild(card);
  }
  body.appendChild(grid);
}
