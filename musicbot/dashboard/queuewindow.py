"""待播清單的視窗：每個瀏覽器只拿前面一段，而且清單沒變就不重送

為什麼需要：清單可以到 5000 首，但每次狀態一變（換歌、有人進出頻道、補到一張縮圖）就重送整份清單，
1000 張卡片是 287 KB，30 次通知就是 8.6 MB 送給一個瀏覽器，經過中繼站時還會吃掉家裡的上傳頻寬

做法：
  1. 視窗：一開始只給 QUEUE_PAGE（100）首，使用者往下捲，網頁再要更多，最多 QUEUE_VIEW（1000）首
  2. 不重送：記住上次送給這個瀏覽器的"是哪個播放器、哪幾首（指紋）"，一樣就把 queue 從訊息裡拿掉，網頁沿用手上那份
     第 2 點只對送過 ``queue_window`` 訊息的瀏覽器生效（新版網頁一連上就會送），舊版網頁每次都拿得到 queue，不會壞

The queue window: each browser gets only the first part of the queue, and an unchanged list is not sent again.

Why: a queue may hold 5000 songs, but every state change (next song, someone joining a channel, one thumbnail arriving)
used to re-send the whole list. 1000 cards are 287 KB, so 30 notifications pushed 8.6 MB to one browser, and through the
relay that also eats the home upload bandwidth.

How:
  1. Window: QUEUE_PAGE (100) songs at first; as the user scrolls the page asks for more, up to QUEUE_VIEW (1000).
  2. No re-send: remember which player and which songs (a fingerprint) this browser got last; when they are the same, the
     ``queue`` key is left out of the message and the page keeps the copy it has.
     Point 2 only applies to browsers that sent a ``queue_window`` message (the current page does so on connect). An older
     page keeps receiving ``queue`` every time, so it never breaks.
"""
from __future__ import annotations

from dataclasses import dataclass

from .. import params


@dataclass
class QueueView:
    """一個瀏覽器的清單視窗 / One browser's view of the queue."""
    limit: int = params.QUEUE_PAGE     # 要看前幾首 / how many songs it wants
    delta: bool = False                # True = 這個瀏覽器懂"沒變就不送" / True = this browser understands "unchanged, not sent"
    seen: tuple | None = None          # 上次送出的 (播放器, 指紋)，None = 還沒送過 / the (player, fingerprint) sent last, None = nothing sent yet

    def ask(self, limit: object) -> None:
        """網頁要求視窗大小（往下捲時會變大），順便代表它懂"沒變就不送"；數字會被限制在 QUEUE_PAGE 到 QUEUE_VIEW 之間

        The page asks for a window size (it grows while scrolling), which also tells us it understands "unchanged, not sent".
        The number is clamped between QUEUE_PAGE and QUEUE_VIEW; anything that isn't a number keeps the current size.
        """
        self.delta = True
        if isinstance(limit, (int, float)) and not isinstance(limit, bool):
            self.limit = int(max(params.QUEUE_PAGE, min(limit, params.QUEUE_VIEW)))

    def trim(self, snap: dict) -> dict:
        """送出前整理快照：拿掉只在伺服器內部用的指紋；清單和上次一樣（且瀏覽器懂）就連 queue 一起拿掉

        Tidy a snapshot before sending: drop the server-side fingerprint, and drop ``queue`` too when it is what this browser
        already has (and the browser understands that).
        """
        if "queue_sig" not in snap:        # 還沒驗證的人拿到的快照沒有清單 / the snapshot of an unverified viewer has no queue
            return snap
        key = (snap.get("selected"), snap.pop("queue_sig"))
        if self.delta and key == self.seen:
            snap.pop("queue", None)
        self.seen = key
        return snap
