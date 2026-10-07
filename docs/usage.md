# Using yt-stash

This page explains every feature and how to use it. New here? Start with the
[quickstart in the README](https://github.com/ilkerkeklik01/yt-stash#quickstart).

**Contents:** [Interactive mode](#interactive) · [Videos](#video-mode--one-or-more-videos) ·
[Playlists](#playlist-mode) · [Quality](#quality-selection) · [Audio only](#audio-only) ·
[Subtitles](#subtitles) · [Members-only videos](authentication.md) · [Resume and skip](#resume-and-skip) ·
[Language](#language--dil) · [Scripting](#scripting) · [All options](#all-options) ·
[Recipes](#recipes)

## Interactive

Run `yt-stash` without arguments to open the main menu. Move with the **↑/↓ arrow keys**
(or `j`/`k`) and press **Enter** to choose; the line under the menu explains the
highlighted entry. Press **Esc** at any question to go back one step: from a setting
to the review screen, from the folder to the quality, and from anything before the
download starts to the main menu.

```text
$ yt-stash
yt-stash 1.0.0  Download YouTube videos and playlists

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
When a download finishes, yt-stash shows the one-line command that repeats it without
questions (handy for scripts), and you can go back to the main menu for more.

Giving a mode and links on the command line (`yt-stash video URL`) skips the main menu
but still shows the review screen; add `--yes` to skip every question.

## Language / Dil

yt-stash speaks **English** and **Turkish (Türkçe)**: menus, messages, progress and
`--help`. Choose **Language** in the main menu to switch at once; the choice is saved for
next time in `config.json` in your settings folder (`%APPDATA%\yt-stash` on Windows,
`~/Library/Application Support/yt-stash` on macOS, `~/.config/yt-stash` on Linux).

The language is taken from, in this order: `--lang en|tr`, the `YT_STASH_LANG` environment
variable, the choice saved from the main menu, your system language (`LC_ALL`/`LANG`, or
the Windows display language), and otherwise English. Flags, quality keywords and command
examples stay English in every language, so scripts work the same everywhere.

## Video mode — one or more videos

```bash
yt-stash video URL                         # asks quality and folder
yt-stash video URL1 URL2 URL3 -j 3         # three videos in parallel
yt-stash video URL -q 720 -o ~/Videos      # no questions about quality/folder
yt-stash video --from-file urls.txt        # one or more URLs per line, '#' comments allowed
```

Accepted forms: `youtube.com/watch?v=…`, `youtu.be/…`, `/shorts/…`, `/live/…`, `/embed/…`,
`music.youtube.com`, or a bare 11-character video id. Duplicates are removed. A
`watch?v=…&list=…` URL downloads only that video in video mode.

## Playlist mode

```bash
yt-stash playlist "https://www.youtube.com/playlist?list=PL..."
yt-stash playlist "https://www.youtube.com/watch?v=xyz&list=PL..." -q best -j 4 -o D:\Videos
```

Videos are saved in a sub-folder named after the playlist and numbered in playlist order
(`01 - Title [id].mp4`). Unavailable entries (deleted/private) are reported and skipped;
everything else is still downloaded.

## Quality selection

- yt-stash first fetches the formats of every video and shows the **union** of all
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

## Audio only

```bash
yt-stash video URL -a                 # m4a (default)
yt-stash video URL -a mp3             # mp3 (needs ffmpeg)
yt-stash video URL -a opus            # opus
yt-stash playlist URL -a mp3 -o ~/Music
```

Audio files are saved next to (and named like) videos but with the audio extension, so you can keep a
video and its audio side by side. In the main menu, the review screen's **Quality** entry also offers
*Audio only*.

## Subtitles

```bash
yt-stash video URL --subs en,tr                 # save .vtt files next to the video
yt-stash video URL --subs en --auto-subs        # also accept auto-generated captions
yt-stash video URL --subs all --embed-subs      # embed every language (needs ffmpeg)
```

## Resume and skip

- Interrupting (Ctrl+C) keeps partial `.part` files; the next run **resumes** them.
  Press Ctrl+C a second time to quit immediately.
- Videos whose final file already exists in the target folder are **skipped** (shown as
  "already downloaded"). Audio and video are separate files (`.mp3` vs `.mp4`), so getting
  the audio of a video you already have works. A deleted file is downloaded again.
- Use `--overwrite` to download again anyway, e.g. in a different quality.
- Temporary failures (network errors, HTTP 429 rate limits) are retried automatically with
  increasing back-off, both while fetching video info and while downloading.

## Scripting

When stdin isn't a terminal, or with `-y/--yes`, yt-stash never asks: it uses your flags or
the defaults (1080p-or-best, `~/Downloads` or the current directory).

| Exit code | Meaning |
|---|---|
| 0 | everything downloaded or already present |
| 1 | at least one video failed or was unavailable |
| 2 | invalid usage (bad URL, flag, cookies, or target folder) |
| 130 | interrupted with Ctrl+C |

## All options

```text
yt-stash [video URL... | playlist URL] [options]

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
  --paste-cookies           paste cookies (or pipe them to stdin); used once, never saved
execution:
  -j, --jobs N              parallel downloads, 1-16 (default 3)
  -y, --yes                 never ask questions
  --list-qualities          show qualities only
  --ffmpeg-location PATH    ffmpeg binary or its folder
  --lang {en,tr}            language of menus and messages
  -v, --verbose             show yt-dlp debug output
```

Options may be given before or after `video`/`playlist`, and also without a subcommand
for interactive mode (e.g. `yt-stash --cookies-from-browser firefox`).

## Recipes

**Download a whole playlist at 720p into a folder, five at a time**

```bash
yt-stash playlist "https://www.youtube.com/playlist?list=PL..." -q 720 -j 5 -o ~/Videos
```

**Back up the audio of a channel's playlist as mp3**

```bash
yt-stash playlist URL -a mp3 --yes -o ~/Music
```

**Download a list of links from a file (one or more per line, `#` for comments)**

```bash
yt-stash video --from-file urls.txt -q 1080 --yes
```

**See what is available before downloading**

```bash
yt-stash video URL --list-qualities
```

**Repeat a run you did interactively**: when a download finishes, yt-stash prints the equivalent
one-line command. Copy it into a script or a scheduled task.

**Run from cron or Task Scheduler**: add `--yes`; the exit code tells you whether everything worked
(see [Scripting](#scripting)). Use an absolute `-o` path.

**Keep subtitles in two languages inside the video file**

```bash
yt-stash video URL --subs en,tr --embed-subs
```

**Re-download in a better quality**

```bash
yt-stash video URL -q 2160 --overwrite
```

Something not working? See [Troubleshooting](troubleshooting.md).
