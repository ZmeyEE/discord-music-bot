"""播放健康偵測：不干擾播放，只在背景"聽"有沒有卡頓；確定是新加入的頻道造成的，就從最後加入的開始，一個一個停掉並公告

分身沒有數量上限；這個偵測器就是把關的人

怎麼不影響播放
- 音訊來源包一層薄薄的"探針"（ProbedSource）：每 20 ms 讀一次封包時只多記錄兩個時間戳，沒有鎖、沒有 I/O
- 偵測器是獨立的背景工作，每 5 秒醒來一次，只讀計數、做幾個加減乘除，它自己不碰語音連線，
  只有"確定要停某個頻道"那一刻才會動作

怎麼判斷"卡頓"
- 正常情況下相鄰兩次讀取相隔約 20 ms，超過 60 ms（README 實測的可聞門檻）就記一次事件；
  間隔超過 1.5 秒是暫停／跳轉，開播前 3 秒是 ffmpeg 暖機，都不算

怎麼避免誤殺（濾波＋歸因＋緩衝）——要"全部"成立才會停掉頻道：
1. 持續：最近 60 秒內至少 4 次事件、分散在至少 3 個不同的 5 秒區間、第一次到最後一次相隔至少 20 秒，
   而且每分鐘 ≥ 6 次，偶爾一次、或一次同時爆出一堆（磁碟／GC 的瞬間卡頓）、或只卡短短一陣都不算
2. 加入前是順的：目前這個"同時播放 N 條"的狀態之前，"N−1 條"的狀態至少觀察過 40 秒，而且很乾淨（每分鐘 ≤ 1.5 次）
3. 加入後才卡的：卡頓在最後一個頻道加入後 5 分鐘內出現（之後才出現的卡頓更可能是電腦別的程式造成的，不怪它）
4. 緩衝：停掉一個之後至少隔 90 秒才會再判斷；而且"因為有頻道離開才開始的狀態"不會再被怪罪——
   停掉一個之後如果還是卡，就代表原因不在新加入的頻道（例如你同時開了遊戲），不會繼續停；
   要等下一次又有新頻道加入，才會重新判斷，所以不可能因為一次卡頓把頻道全部停光，永遠至少保留 1 個頻道
5. 停掉之後 10 分鐘內不再派新的頻道進來（避免剛停掉又馬上加回去、再卡一次）

Playback health monitor: it never interferes with playback; it just "listens" in the background for stutter.
When it is certain that a newly added channel caused it, it stops channels one at a time, newest first,
and announces each removal.

Clones have no upper limit; this monitor is the gatekeeper.

How it stays out of the way
- The audio source is wrapped in a thin "probe" (ProbedSource): each 20 ms packet read only records two
  timestamps. No locks, no I/O.
- The monitor is a separate background task that wakes every 5 s, reads counters and does a little
  arithmetic. It never touches voice connections itself, except at the moment it decides to stop a channel.

How a "stutter" is defined
- Normally two consecutive reads are ~20 ms apart. A gap above 60 ms (the audible threshold measured in the
  README) counts as one event. Gaps above 1.5 s mean pause/seek, and the first 3 s of a song is ffmpeg
  warm-up; neither counts.

How wrongful removals are avoided (filtering + attribution + buffering) - ALL of these must hold:
1. Sustained: >= 4 events in the last 60 s, spread over >= 3 different 5 s slots, first-to-last event >= 20 s
   apart, and >= 6 events per minute. A one-off, a single burst (disk / GC hiccup) or a short blip doesn't count.
2. Smooth before: before the current "N streams playing" state, the "N-1 streams" state was observed for
   >= 40 s and was clean (<= 1.5 events per minute).
3. Stutter after joining: it started within 5 minutes of the last channel joining (later stutter is more
   likely caused by other programs on the PC, so the newcomer isn't blamed).
4. Buffering: after one removal, wait >= 90 s before judging again; and a state that began because a channel
   *left* is never blamed - if it still stutters after a removal, the cause isn't the newcomer (maybe you
   launched a game), so it stops removing until another channel joins. A single hiccup therefore can never
   wipe out all channels. At least 1 channel is always kept.
5. For 10 minutes after a removal no new channel is assigned (avoids re-adding it straight away and stuttering again).

檔案 / files:
  probe.py    量測 / measuring
  ledger.py   判斷 / judging
  monitor.py  背景監看 / background monitor
"""
from .ledger import Evidence, Ledger, Removal, Sample
from .monitor import HealthMonitor
from .probe import CpuSampler, ProbedSource, StreamProbe, probe_source

__all__ = ["StreamProbe", "ProbedSource", "probe_source", "CpuSampler", "Evidence", "Ledger", "Sample", "Removal", "HealthMonitor"]
