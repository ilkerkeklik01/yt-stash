# ytgrab

A cross-platform (Linux, macOS, Windows) command-line YouTube downloader for single
videos, multiple videos and whole playlists, including **members-only and private videos**.

- **Every quality**: detects all available resolutions (144p … 4320p/8K, high frame rate, HDR)
  and lets you choose. Defaults to **1080p**, or the **highest available** when 1080p isn't offered.
- **Video & playlist modes**: one or many video URLs, or every video of a playlist.
- **Parallel downloads**: several videos at once, plus parallel fragment downloads per video.
- **Members-only / private / age-restricted** videos via your browser's signed-in session
  or a `cookies.txt` file. If a video needs sign-in, ytgrab asks you and retries.
- **Audio only** (m4a, mp3, opus), **subtitles** (download or embed),
  **resume** of interrupted downloads and **skipping** of already downloaded videos.
- Interactive by default, fully scriptable with flags (`--yes`) for cron/CI.

It is built on [yt-dlp](https://github.com/yt-dlp/yt-dlp), the best-maintained YouTube
extraction library, so it keeps working when YouTube changes.

---

## Installation

### 1. Requirements

| Requirement | Why | Install |
|---|---|---|
| Python ≥ 3.10 | runs ytgrab | [python.org](https://www.python.org/downloads/) |
| **ffmpeg** (strongly recommended) | merges the separate video+audio streams YouTube uses for everything above 360p; converts audio; embeds subtitles | macOS: `brew install ffmpeg` · Windows: `winget install Gyan.FFmpeg` · Debian/Ubuntu: `sudo apt install ffmpeg` · Fedora: `sudo dnf install ffmpeg` |
| **deno** (recommended) or node / bun | YouTube requires a JavaScript runtime to unlock most formats | macOS/Linux: `curl -fsSL https://deno.land/install.sh \| sh` · Windows: `winget install DenoLand.Deno` · or `brew install deno` |

ytgrab works without ffmpeg/deno but warns you, because quality will be limited.

### 2. Install ytgrab

Using [pipx](https://pipx.pypa.io/) (recommended — isolated, puts `ytgrab` on your PATH):

```bash
pipx install git+https://github.com/ilkerkeklik01/youtube-downloader.git
```

Or from a clone:

```bash
git clone https://github.com/ilkerkeklik01/youtube-downloader.git
cd youtube-downloader
python -m venv .venv
# macOS/Linux:  source .venv/bin/activate
# Windows:      .venv\Scripts\activate
pip install .
```

Check it works: `ytgrab --version`

> **Keep yt-dlp fresh.** YouTube changes often; if downloads suddenly fail, update with
> `pipx upgrade ytgrab` / `pip install -U yt-dlp`.

---

## Usage

### Interactive

Run `ytgrab` without arguments to open the main menu. Move with the **↑/↓ arrow keys**
(or `j`/`k`) and press **Enter** to choose; the line under the menu explains the
highlighted entry. Press **Esc** at any question to go back one step: from a setting
to the review screen, from the folder to the quality, and from anything before the
download starts to the main menu.

```text
$ ytgrab
ytgrab 1.0.0  Download YouTube videos and playlists

▶ What do you want to do? (↑↓ to move, Enter to choose)
 ❯ Download videos
   Download a playlist
   Download links from a text file
   Show available qualities

   Sign-in (off)
   Language (English)
   Check setup
   Command-line options
   Quit
  Description: Paste one or more video links.
```

After you choose a quality and a folder, a review screen lists every setting. Press
Enter to start, or move to a setting to change it: quality or audio only, folder,
video format (mp4/mkv/webm), subtitles, what to do with files you already have, and
how many videos download at the same time.

```text
▶ Ready to download 2 videos (↑↓ to move, Enter to choose, Esc to go back)
 ❯ Start download

   Quality              1080p (or closest lower)
   Save to              ~/Downloads
   Video format         mp4
   Subtitles            off
   Existing files       skip
   Parallel downloads   2 at a time

   Cancel
```

Folders and files are picked in a browser: Enter opens a folder, `..` goes up, typing
filters the list, and shortcuts jump to your Home, Downloads, Desktop and Videos folders.
You can also create a new folder there or type a path. **Check setup** and
**Command-line options** open as full-screen pages; scroll with the arrow keys or
PgUp/PgDn and leave with Esc or `q`.

Links are checked as you type, so a mistyped link is reported before anything starts.
When a download finishes, ytgrab shows the one-line command that repeats it without
questions (handy for scripts), and you can go back to the main menu for more.

Giving a mode and links on the command line (`ytgrab video URL`) skips the main menu
but still shows the review screen; add `--yes` to skip every question.

### Language / Dil

ytgrab speaks **English** and **Turkish (Türkçe)**: menus, messages, progress and
`--help`. Choose **Language** in the main menu to switch at once; the choice is saved for
next time in `config.json` in your settings folder (`%APPDATA%\ytgrab` on Windows,
`~/Library/Application Support/ytgrab` on macOS, `~/.config/ytgrab` on Linux).

The language is taken from, in this order: `--lang en|tr`, the `YTGRAB_LANG` environment
variable, the choice saved from the main menu, your system language (`LC_ALL`/`LANG`, or
the Windows display language), and otherwise English. Flags, quality keywords and command
examples stay English in every language, so scripts work the same everywhere.

### Video mode — one or more videos

```bash
ytgrab video URL                         # asks quality and folder
ytgrab video URL1 URL2 URL3 -j 3         # three videos in parallel
ytgrab video URL -q 720 -o ~/Videos      # no questions about quality/folder
ytgrab video --from-file urls.txt        # one or more URLs per line, '#' comments allowed
```

Accepted forms: `youtube.com/watch?v=…`, `youtu.be/…`, `/shorts/…`, `/live/…`, `/embed/…`,
`music.youtube.com`, or a bare 11-character video id. Duplicates are removed. A
`watch?v=…&list=…` URL downloads only that video in video mode.

### Playlist mode

```bash
ytgrab playlist "https://www.youtube.com/playlist?list=PL..."
ytgrab playlist "https://www.youtube.com/watch?v=xyz&list=PL..." -q best -j 4 -o D:\Videos
```

Videos are saved in a sub-folder named after the playlist and numbered in playlist order
(`01 - Title [id].mp4`). Unavailable entries (deleted/private) are reported and skipped;
everything else is still downloaded.

### Quality selection

- ytgrab first fetches the formats of every video and shows the **union** of all
  resolutions, with how many videos offer each one.
- You choose **once** for the whole batch. Each video is downloaded at that resolution,
  or the **closest lower** one it has (or its lowest, if it only has higher ones), so a
  batch never fails because one video lacks a resolution.
- Default: **1080p**, or the **highest available** if no video offers 1080p.
- Flags: `-q 2160`, `-q 720p`, `-q best`, `-q worst`, `-a` / `--audio-only [m4a|mp3|opus]`.
- `--list-qualities` only shows the table.
- Vertical videos (Shorts) are labelled by their short side, like YouTube does (1080x1920 = 1080p).

Files are `.mp4` by default (H.264/AAC preferred at equal resolution for maximum
compatibility). Resolutions above 1080p are only available as VP9/AV1; those are put in
mp4 when possible and in `.mkv` otherwise. Use `--container mkv|webm` to choose.

### Members-only, private and age-restricted videos

YouTube doesn't allow password logins from third-party tools, so ytgrab uses the cookies
of a browser where you are **signed in to YouTube** (with an active membership for
members-only content):

```bash
ytgrab video URL --cookies-from-browser firefox
ytgrab video URL --cookies-from-browser "chrome:Profile 1"      # a specific profile
ytgrab playlist URL --cookies-from-browser edge
ytgrab video URL --cookies ~/cookies.txt                         # exported cookies file
```

Supported browsers: brave, chrome, chromium, edge, firefox, opera, safari, vivaldi, whale.
Full syntax: `BROWSER[+KEYRING][:PROFILE][::CONTAINER]` (same as yt-dlp).

If you don't pass any of these and a video turns out to need sign-in, ytgrab **asks you**
(interactive mode) for a browser or cookies file and retries just those videos.

Tip — download all members-only videos of a channel: take the channel id (`UCxxxx…`),
replace the `UC` prefix with `UUMO`, and use it as a playlist:
`ytgrab playlist "https://www.youtube.com/playlist?list=UUMOxxxx…" --cookies-from-browser firefox`.

Platform notes:

- **Firefox** works on every OS and is the most reliable choice.
- **Chrome/Edge on Windows** may refuse cookie access while the browser is running (app-bound
  encryption). Close the browser, use Firefox, or export a `cookies.txt` instead.
- **Safari (macOS)** requires granting your terminal *Full Disk Access*
  (System Settings → Privacy & Security).
- **macOS keychain**: Chromium-based browsers may trigger one keychain prompt; ytgrab reads
  cookies once and shares them with all parallel downloads.
- **Exporting cookies.txt**: use a browser extension that exports Netscape-format cookies
  while you are on youtube.com. Treat this file like a password and never share it.

ytgrab never modifies your browser data or your cookies file.

### Subtitles

```bash
ytgrab video URL --subs en,tr                 # save .vtt files next to the video
ytgrab video URL --subs en --auto-subs        # also accept auto-generated captions
ytgrab video URL --subs all --embed-subs      # embed every language (needs ffmpeg)
```

### Resume and skip

- Interrupting (Ctrl+C) keeps partial `.part` files; the next run **resumes** them.
  Press Ctrl+C a second time to quit immediately.
- Videos whose final file already exists in the target folder are **skipped** (shown as
  "already downloaded"). Audio and video are separate files (`.mp3` vs `.mp4`), so getting
  the audio of a video you already have works. A deleted file is downloaded again.
- Use `--overwrite` to download again anyway, e.g. in a different quality.
- Temporary failures (network errors, HTTP 429 rate limits) are retried automatically with
  increasing back-off, both while fetching video info and while downloading.

### Scripting

When stdin isn't a terminal, or with `-y/--yes`, ytgrab never asks: it uses your flags or
the defaults (1080p-or-best, `~/Downloads` or the current directory).

| Exit code | Meaning |
|---|---|
| 0 | everything downloaded or already present |
| 1 | at least one video failed or was unavailable |
| 2 | invalid usage (bad URL, flag, cookies, or target folder) |
| 130 | interrupted with Ctrl+C |

### All options

```text
ytgrab [video URL... | playlist URL] [options]

output:
  -o, --output DIR          target directory (asked if omitted)
  -q, --quality Q           2160, 1080, 720p, best, worst ... (default 1080p, else highest)
  -a, --audio-only [FMT]    audio only: m4a (default), mp3, opus
  --container {mp4,mkv,webm}
  --overwrite               download again even if the file already exists
  --from-file FILE          read URLs from a text file
subtitles:
  --subs LANGS              e.g. en,tr or all
  --auto-subs               accept auto-generated subtitles
  --embed-subs              embed into the video file
authentication:
  --cookies-from-browser BROWSER[+KEYRING][:PROFILE][::CONTAINER]
  --cookies FILE
execution:
  -j, --jobs N              parallel downloads, 1-16 (default 3)
  -y, --yes                 never ask questions
  --list-qualities          show qualities only
  --ffmpeg-location PATH    ffmpeg binary or its folder
  --lang {en,tr}            language of menus and messages
  -v, --verbose             show yt-dlp debug output
```

Options may be given before or after `video`/`playlist`, and also without a subcommand
for interactive mode (e.g. `ytgrab --cookies-from-browser firefox`).

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Only 360p or lower is offered | Install **ffmpeg** and **deno** (see Requirements). |
| "Sign in to confirm you're not a bot" | Use `--cookies-from-browser`; lower `-j`; wait a while. |
| "rate limited" / HTTP 429 | ytgrab retries automatically with back-off; use fewer parallel jobs (`-j 1`). |
| "Could not load cookies" | Close the browser (Windows Chrome/Edge), pick the right profile, or use `--cookies`. |
| Members-only video still fails with cookies | The signed-in account must have an active membership of that channel. |
| Anything else | Run with `-v` and update yt-dlp: `pip install -U yt-dlp`. |

---

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                      # fast, offline test suite
pytest -m network           # real downloads from YouTube (needs internet)
pytest --cov                # coverage report
ruff check . && ruff format --check .
```

The architecture is described in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

Please only download content you have the right to download and respect YouTube's Terms
of Service and the creators' rights.
