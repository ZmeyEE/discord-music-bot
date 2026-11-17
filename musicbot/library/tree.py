"""我的歌單的資料夾樹：純函式，不碰檔案、不碰網路，所以很好測

樹的樣子：
  根（資料夾）
   ├─ 資料夾 "華語"        {"type": "folder", "children": [...]}   可以再放資料夾和歌單，最多 LIB_MAX_DEPTH 層
   │    └─ 歌單 "抒情"     {"type": "playlist", "songs": [...]}     歌單裡才放歌
   └─ 歌單 "跑步用"
一首歌存的是連結和顯示用的資料：{"url", "title", "duration", "thumbnail", "uploader", "search"}（search 是 Spotify 的歌用來找對應影片的關鍵字）

The folder tree of a person's library: pure functions, no files and no network, so it is easy to test.
Folders hold folders and playlists (nesting up to LIB_MAX_DEPTH); only playlists hold songs.
A song is a link plus what is needed to show it: url, title, duration, thumbnail, uploader, and ``search`` (the keywords a Spotify song uses to find its video).
"""
from __future__ import annotations

import uuid

from .. import params

Node = dict
SONG_KEYS = ("url", "title", "duration", "thumbnail", "uploader", "search")


class LibraryError(ValueError):
    """操作不合法（訊息可以直接給使用者看）/ An illegal operation (the message can be shown to the user as is)."""


def new_id() -> str:
    return uuid.uuid4().hex[:8]


def new_root() -> Node:
    """一棵空的樹 / An empty tree."""
    return {"id": "root", "type": "folder", "name": "", "children": []}


def clean_name(name: object, fallback: str) -> str:
    """名稱：去掉頭尾空白、只留一行、限制長度；空的用 fallback / A name: trimmed, one line, length-limited; ``fallback`` when empty."""
    text = " ".join(str(name or "").split())[: params.LIB_NAME_MAX]
    return text or fallback


def clean_song(raw: dict) -> dict | None:
    """把一首歌整理成要存的樣子；沒有連結就不要 / Normalise one song for storage; ``None`` when it has no link."""
    url = str(raw.get("url") or "").strip()[:500]
    if not url:
        return None
    duration = raw.get("duration")
    return {
        "url": url,
        "title": str(raw.get("title") or url)[:200],
        "duration": int(duration) if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration > 0 else None,
        "thumbnail": str(raw.get("thumbnail") or "")[:500],
        "uploader": str(raw.get("uploader") or "")[:100],
        "search": str(raw.get("search") or "")[:200],
    }


def walk(node: Node):
    """走過整棵樹（含自己），先上後下 / Every node in the subtree, the node itself first."""
    yield node
    for child in node.get("children", ()):
        yield from walk(child)


def find(root: Node, node_id: str) -> Node | None:
    """用 id 找節點 / Find a node by id."""
    return next((n for n in walk(root) if n["id"] == node_id), None)


def parent_of(root: Node, node_id: str) -> Node | None:
    """某個節點的上一層；根沒有 / The parent of a node; the root has none."""
    return next((n for n in walk(root) if any(c["id"] == node_id for c in n.get("children", ()))), None)


def depth_of(root: Node, node_id: str) -> int:
    """節點在第幾層（根的子節點是 1）/ How deep a node is (a child of the root is 1)."""
    d, cur = 0, find(root, node_id)
    while cur is not None and cur["id"] != root["id"]:
        d += 1
        cur = parent_of(root, cur["id"])
    return d


def height_of(node: Node) -> int:
    """這個節點底下還有幾層資料夾（沒有子資料夾 = 0）/ How many folder levels are below this node (0 when it has no sub-folders)."""
    kids = [height_of(c) + 1 for c in node.get("children", ()) if c["type"] == "folder"]
    return max(kids, default=0)


def count_songs(root: Node) -> int:
    return sum(len(n.get("songs", ())) for n in walk(root))


def count_nodes(root: Node) -> int:
    return sum(1 for n in walk(root)) - 1


def songs_of(node: Node) -> list[dict]:
    """節點底下所有的歌，依畫面上的順序（資料夾由上到下、歌單由前到後）/ Every song under a node in on-screen order."""
    if node["type"] == "playlist":
        return list(node.get("songs", ()))
    out: list[dict] = []
    for child in node.get("children", ()):
        out.extend(songs_of(child))
    return out


def _folder(root: Node, folder_id: str) -> Node:
    node = find(root, folder_id)
    if node is None or node["type"] != "folder":
        raise LibraryError("找不到這個資料夾")
    return node


def _check_room(root: Node) -> None:
    if count_nodes(root) >= params.LIB_MAX_NODES:
        raise LibraryError(f"資料夾和歌單太多了（上限 {params.LIB_MAX_NODES} 個）")


def add_folder(root: Node, parent_id: str, name: str) -> Node:
    """在 parent 裡建一個資料夾 / Create a folder inside a parent folder."""
    parent = _folder(root, parent_id)
    if parent["id"] != root["id"] and depth_of(root, parent["id"]) >= params.LIB_MAX_DEPTH:
        raise LibraryError(f"資料夾最多 {params.LIB_MAX_DEPTH} 層")
    _check_room(root)
    node = {"id": new_id(), "type": "folder", "name": clean_name(name, "新資料夾"), "children": []}
    parent["children"].append(node)
    return node


def add_playlist(root: Node, parent_id: str, name: str, songs: list[dict]) -> Node:
    """在 parent 裡建一張歌單並放進這些歌 / Create a playlist inside a folder and fill it with these songs."""
    parent = _folder(root, parent_id)
    _check_room(root)
    node = {"id": new_id(), "type": "playlist", "name": clean_name(name, "新歌單"), "songs": []}
    parent["children"].append(node)
    add_songs(root, node["id"], songs)
    return node


def add_songs(root: Node, playlist_id: str, songs: list[dict]) -> int:
    """把歌放進歌單，回傳實際放進幾首（受上限限制，沒連結的略過）/ Put songs into a playlist; returns how many fit (limits apply, link-less songs are skipped)."""
    node = find(root, playlist_id)
    if node is None or node["type"] != "playlist":
        raise LibraryError("找不到這張歌單")
    room = params.LIB_MAX_SONGS - count_songs(root)
    if room <= 0:
        raise LibraryError(f"存的歌太多了（上限 {params.LIB_MAX_SONGS} 首）")
    added = 0
    for raw in songs:
        song = clean_song(raw)
        if song is None or added >= room:
            continue
        node["songs"].append(song)
        added += 1
    return added


def remove_songs(root: Node, playlist_id: str, indexes: list[int]) -> int:
    """依位置從歌單移除歌 / Remove songs from a playlist by position."""
    node = find(root, playlist_id)
    if node is None or node["type"] != "playlist":
        raise LibraryError("找不到這張歌單")
    drop = {i for i in indexes if isinstance(i, int) and 0 <= i < len(node["songs"])}
    node["songs"] = [s for i, s in enumerate(node["songs"]) if i not in drop]
    return len(drop)


def reorder_song(root: Node, playlist_id: str, frm: int, to: int) -> None:
    """歌單裡把第 frm 首搬到第 to 首的位置 / Move the song at ``frm`` to position ``to`` inside a playlist."""
    node = find(root, playlist_id)
    if node is None or node["type"] != "playlist":
        raise LibraryError("找不到這張歌單")
    songs = node["songs"]
    if not (0 <= frm < len(songs)):
        return
    songs.insert(max(0, min(to, len(songs) - 1)), songs.pop(frm))


def move_songs(root: Node, playlist_id: str, indexes: list[int], to_id: str) -> int:
    """把歌單裡的幾首歌搬到另一張歌單最後面（總數不變，所以不受上限影響）/ Move songs to the end of another playlist (the total is unchanged, so no limit applies)."""
    src, dst = find(root, playlist_id), find(root, to_id)
    if src is None or src["type"] != "playlist" or dst is None or dst["type"] != "playlist":
        raise LibraryError("找不到這張歌單")
    if src["id"] == dst["id"]:
        return 0
    pick = sorted({i for i in indexes if isinstance(i, int) and 0 <= i < len(src["songs"])})
    dst["songs"].extend(src["songs"][i] for i in pick)
    gone = set(pick)
    src["songs"] = [s for i, s in enumerate(src["songs"]) if i not in gone]
    return len(pick)


def rename(root: Node, node_id: str, name: str) -> None:
    node = find(root, node_id)
    if node is None or node["id"] == root["id"]:
        raise LibraryError("找不到這個項目")
    node["name"] = clean_name(name, node["name"])


def delete(root: Node, ids: list[str]) -> int:
    """刪除這些節點（連同裡面的東西），回傳刪了幾個頂層項目 / Delete these nodes with everything inside; returns how many top-level items went."""
    gone = 0
    for node_id in ids:
        if node_id == root["id"]:
            continue
        parent = parent_of(root, node_id)
        if parent is None:
            continue                       # 已經跟著上層一起刪了 / it already went with its parent
        parent["children"] = [c for c in parent["children"] if c["id"] != node_id]
        gone += 1
    return gone


def move(root: Node, ids: list[str], to_id: str, index: int | None = None) -> int:
    """把這些節點搬進另一個資料夾（不能搬進自己或自己的底下）；給 index 就放在那個位置（同一個資料夾內就是重新排序）
    Move nodes into another folder (never into themselves or something below them); with ``index`` they land at that position (inside the same folder that is a reorder)."""
    target = _folder(root, to_id)
    picked: list[Node] = []
    for node_id in ids:
        node = find(root, node_id)
        if node is None or node["id"] == root["id"]:
            continue
        if node["type"] == "folder":
            if any(n["id"] == target["id"] for n in walk(node)):
                raise LibraryError("不能把資料夾搬進它自己裡面")
            base = 0 if target["id"] == root["id"] else depth_of(root, target["id"])
            if base + 1 + height_of(node) > params.LIB_MAX_DEPTH:
                raise LibraryError(f"資料夾最多 {params.LIB_MAX_DEPTH} 層")
        old = parent_of(root, node_id)
        if old is None or (old["id"] == target["id"] and index is None) or any(n["id"] == node["id"] for n in picked):
            continue
        picked.append(node)
    gone = {n["id"] for n in picked}
    for old in {id(parent_of(root, n["id"])): parent_of(root, n["id"]) for n in picked}.values():   # 先全部拿下來，再一起放回去，位置才是"最後的樣子" / take them all out first, then put them in together, so the position is the final one
        old["children"] = [c for c in old["children"] if c["id"] not in gone]
    kids = target["children"]
    at = len(kids) if index is None else max(0, min(int(index), len(kids)))
    kids[at:at] = picked
    return len(picked)


def group(root: Node, ids: list[str], name: str) -> Node:
    """多選的項目一起放進一個新資料夾；新資料夾建在第一個被選項目原本的位置 / Put the selected items into a new folder, created where the first selected item sat."""
    items = [find(root, i) for i in ids]
    items = [n for n in items if n is not None and n["id"] != root["id"]]
    if not items:
        raise LibraryError("請先選要放進資料夾的項目")
    parent = parent_of(root, items[0]["id"]) or root
    folder = add_folder(root, parent["id"], name)
    parent["children"].remove(folder)
    at = next((i for i, c in enumerate(parent["children"]) if c["id"] == items[0]["id"]), len(parent["children"]))
    parent["children"].insert(at, folder)
    move(root, [n["id"] for n in items], folder["id"])
    return folder


def next_sibling_folder(root: Node, node_id: str) -> Node | None:
    """同一層的下一個資料夾，到底了就繞回第一個（只有自己時回傳自己）；"跨資料夾循環"用

    The next folder on the same level, wrapping around to the first (the node itself when it is alone); used by "loop across folders".
    """
    parent = parent_of(root, node_id)
    if parent is None:
        return None
    folders = [c for c in parent["children"] if c["type"] == "folder"]
    ids = [f["id"] for f in folders]
    if node_id not in ids:
        return None
    return folders[(ids.index(node_id) + 1) % len(folders)]


def outline(node: Node) -> dict:
    """給網頁看的樣子：資料夾和歌單的名稱、數量、封面，不含每一首歌 / What the page sees: names, counts and covers, without every song."""
    if node["type"] == "playlist":
        songs = node.get("songs", ())
        covers = [s["thumbnail"] for s in songs[:12] if s.get("thumbnail")][:4]
        return {"id": node["id"], "type": "playlist", "name": node["name"], "count": len(songs), "covers": covers}
    return {"id": node["id"], "type": "folder", "name": node["name"], "count": len(songs_of(node)),
            "children": [outline(c) for c in node.get("children", ())]}
