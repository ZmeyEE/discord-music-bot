# Developer guide (English)

A free Discord music bot that runs on your own PC, Bilibili first, best audio quality, plus a card-style web dashboard
This page is for people who want to change it: new language, new colors, better audio, or reuse the UI somewhere else
(中文版在 [DEVELOPING.zh-TW.md](DEVELOPING.zh-TW.md))

Version: **1.0.0** · License: [Unlicense](../LICENSE) (public domain, do whatever you want) · Third-party list: [THIRD_PARTY.md](../THIRD_PARTY.md)

## 1. Map of the project

```
bot.py                 entry point, only calls musicbot.app.main()
musicbot/
  app.py               start-up: read config, make Hub, dashboard, relay client, health monitor, log in every bot
  hub.py               the brain: permissions, snapshots for the dashboard, actions (add, skip, seek...)
  player.py            one Discord bot account = one PlayerBot (queue, ffmpeg, voice)
  sources.py           yt-dlp: URL / keywords -> tracks -> audio stream
  bilibili.py          Bilibili QR login, account info
  dashboard.py         local web server (static files + WebSocket) and DashboardCore
  relay.py             optional relay (VPS / Raspberry Pi), only forwards messages
  relay_client.py      the bot at home dials out to the relay
  health.py            stutter detector, stops channels one by one (newest first) when the PC can't keep up
  commands.py          slash commands (/play /help /quality ...)
  auth.py members.py   signed links, remembered devices (hash only)
  config.py paths.py   .env, settings.json, quality, ffmpeg lookup, file locations
web/                   dashboard front-end, vanilla HTML / CSS / JS, no build step
tests/                 regression tests (fake Discord voice layer)
launcher/              tiny desktop start/stop window (tkinter, optional)
deploy/                systemd service for the relay
```

Rule of thumb: **one Discord bot account = one voice channel per server**, so extra channels need clone accounts
(`add-clone.bat`), and `Hub` coordinates all of them

## 2. Set up

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt      # Linux / macOS: .venv/bin/python
copy .env.example .env                                           # then put your DISCORD_TOKEN in it
.venv\Scripts\python.exe bot.py
```

You also need ffmpeg (on PATH, or `FFMPEG_PATH` in `.env`)
Never commit `.env`, `cookies.txt`, `settings.json`, `members.json` (already in `.gitignore`)

## 3. Run the tests

```bash
.venv\Scripts\python.exe tests\run_all.py              # everything
.venv\Scripts\python.exe tests\run_all.py verify       # only suites whose name contains "verify"
.venv\Scripts\python.exe tests\run_relay.py            # relay suites
```

The tests start the real `Hub`, `Dashboard` and `PlayerBot` and only fake the Discord voice layer (`tests/harness_hub.py`)
They need network (they resolve one Bilibili video) and ffmpeg, they never touch your real `settings.json` or `members.json`
Details in [tests/README.md](../tests/README.md)

Please run them before every pull request, and add a test when you add a feature

## 4. Change the colors (background, cards, fonts)

Everything visual is in `web/style.css`, the colors are tokens at the very top

```css
:root {
  --cream: #F7E0D3;  --rose: #E3C2C6;  --lavender: #AFAFC8;  --steel: #5F7EAE;   /* palette */
  --ink: #33405E;    --accent: #54739F;                                          /* text, buttons */
  --card: #FFF9F4;   --radius: 18px;                                             /* cards */
  --font: "Huninn", ...;                                                         /* fonts */
}
```

- **Palette / text / buttons / card color**: edit the tokens in `:root`, every part of the page follows
- **Background**: the sky is a gradient on `body::before` (a fixed layer, painted once so scrolling and dragging stay smooth), change the `linear-gradient(...)` and the two `radial-gradient(...)` there
- **Fonts**: `--font` and `--font-num`, the Google Fonts `<link>` lines are at the top of `web/index.html` (remove them if you don't want the browser to contact Google, it falls back to system fonts)
- **Icons**: hand-drawn SVG sprite at the top of `web/index.html`, used as `<svg class="i"><use href="#i-name"/></svg>` (or `icon("name")` in `app.js`)
- Keep text contrast readable (the default text color is > 7:1, white on buttons > 4.5:1)
- No build step, just save the file and refresh the browser

## 5. Add a language

Honest status for 1.0.0: **there is no i18n layer yet**, all texts are written directly in the code (Traditional Chinese)
So today a new language means editing strings, and an i18n layer is the best first contribution

Where the texts live (rough count of lines with visible text):

| Where | What | Lines |
| --- | --- | --- |
| `web/index.html` | labels, buttons, tooltips | ~44 |
| `web/app.js` | toasts, status text, dialogs | ~94 |
| `musicbot/commands.py` | slash command names, descriptions, replies | ~73 |
| `musicbot/hub.py` `player.py` `dashboard.py` `app.py` `health.py` `relay.py` | announcements, errors, log lines | ~180 |

Find them yourself with a CJK search, for example `rg "[一-鿿]" web musicbot`

Suggested plan if you want to do it properly:

1. **Web**: add `web/i18n/<lang>.js` (a plain object `{ "key": "text" }`), a tiny `t(key)` in `app.js`, mark HTML with `data-i18n="key"`, pick the language from `navigator.language` (or a `?lang=` / saved choice)
2. **Server replies**: move the strings in `commands.py` / `hub.py` / `player.py` into one `messages.py` keyed by id, with the language chosen by a `.env` setting (for example `BOT_LANG=en`)
3. **Slash commands**: discord.py supports command localization (`app_commands.locale_str` + a `Translator`), use it so each user sees commands in their own Discord language
4. Keep the Chinese as the default so nothing changes for current users, add a test that every key exists in every language file

If you only need one other language for yourself, the quick way is a find-and-replace on the table above, then check with the tests

## 6. Improve the audio path (source → Discord)

```
URL --> sources.resolve_tracks --> queue --> player.ensure_playing --> sources.extract_stream (yt-dlp)
    --> player._play_stream (ffmpeg -> Opus) --> Discord voice
```

- **Which track yt-dlp picks**: `sources.extract_stream`, the `"format"` string, now `bestaudio[acodec=flac]/bestaudio[acodec!*=ec-3]/bestaudio/best` (lossless FLAC if the account can get it, then best normal track, skipping Dolby E-AC-3 because down-mixing makes it worse)
- **Bilibili login / premium (大會員)**: `bilibili.py` writes `cookies.txt`, `sources.py` hands it to yt-dlp, a premium account is what unlocks lossless Hi-Res (this path is **not tested** by the author, no premium account)
- **How ffmpeg is called**: `player.PlayerBot._play_stream`
  - `before_options`: reconnect flags, request headers, `-ss` for seeking (before `-i` = fast seek)
  - `options="-vn"`: drop video, put extra output flags here, for example a loudness filter `-af loudnorm`
  - No codec is given, so discord.py re-encodes with libopus at the bitrate we pass (Discord only accepts Opus, so there is always one re-encode, the goal is "best source → highest Opus bitrate")
- **Bitrate**: `config.target_bitrate()` = the higher of the server's quality setting and the voice channel's own bitrate, clamped to Opus' 8 - 510 kbps, choices in `config.QUALITY_CHOICES`
- **Stutter detection**: `health.py` wraps the audio source (`probe_source`) and only measures packet timing, it never changes the audio, keep it that way when you change the path
- After any change, listen to it, then run `tests\run_all.py quality` and `seek`

Gotchas: `davey` must stay `<0.2` with discord.py 2.7.x (otherwise the bot joins voice but nobody hears anything), sites change often so try `update-ytdlp.bat` first when searching or playing breaks

## 7. Use the dashboard UI somewhere else

The front-end is vanilla HTML / CSS / JS, only [SortableJS](https://github.com/SortableJS/Sortable) is bundled
It talks to the backend through **one WebSocket** (`/ws/<guild id>`) with small JSON messages, so any backend that speaks the same messages can drive it

Server → browser:

| `type` | meaning |
| --- | --- |
| `state` | full state: now playing, queue, channels, permissions (`me`), quality, Bilibili account (built by `Hub.snapshot`) |
| `toast` | a short message to show |
| `error` | something is wrong (`code`: `guild`, `auth`, `offline`...) |
| `verified` / `revoked` | device token issued / taken back (verify mode) |

Browser → server (`Hub.handle_action` and `DashboardCore`):

`add` `move` `remove` `remove_current` `play_now` `skip` `seek` `toggle_pause` `stop` `shuffle` `clear` `loop` `quality` `select` `bili_login_start` `bili_login_cancel` `bili_logout`

Ideas:

- **Other music source / other chat platform**: keep `web/` as is, write a backend that serves `web/` plus `/ws/<id>` and builds the same `state` object
- **Only the card look**: copy `.card` and its children from `web/style.css`, `makeCard()` in `web/app.js` and the palette tokens, they have no dependency on the music code
- **Drag to reorder / drag to the trash**: see the Sortable setup in `app.js` and `.trash` in the CSS
- A standalone "card UI" library made from these parts is a planned follow-up, not part of 1.0.0

## 8. Security rules for contributors

- Never put tokens, cookies, IDs, IPs or personal paths in code, comments, tests or screenshots
- Keep permission checks on the **server** (`Hub.can_control`), the browser is never trusted
- Any new endpoint on the relay needs rate limits and a test in `tests/harden_test.py`
- Before a release run the secret scan and a dependency audit (`pip-audit`), see [SECURITY.md](../SECURITY.md)

## 9. Releasing

1. Bump `__version__` in `musicbot/__init__.py` ([SemVer](https://semver.org/): fix = patch, feature = minor, breaking = major)
2. Add the changes to [CHANGELOG.md](../CHANGELOG.md)
3. Run all tests, tag `vX.Y.Z`, create a GitHub release

## 10. Code style

- Comments in two languages (中文 / English), short and friendly, explain **why**, not only what
- Chinese comments follow the project style: commas and straight quotes, no corner brackets and no full stops
- Small functions, one job each, a docstring for every function
