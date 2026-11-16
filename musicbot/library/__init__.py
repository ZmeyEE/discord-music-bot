"""我的歌單：每位 Discord 使用者自己的資料夾與歌單

  tree.py   資料夾樹的純函式（建立、改名、搬移、多選成資料夾、循環用的"下一個資料夾"…）
  store.py  存檔（library.json，原子寫入）

網頁操作的處理在 musicbot/hub/library.py，畫面在 web/js/library.js

My library: each Discord user's own folders and playlists.
  tree.py   pure folder-tree functions (create, rename, move, group a selection into a folder, the "next folder" for looping...)
  store.py  persistence (library.json, atomic writes)
The handling of dashboard actions is musicbot/hub/library.py; the screen is web/js/library.js.
"""
from .store import Library
from .tree import LibraryError

__all__ = ["Library", "LibraryError"]
