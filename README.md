<div align="center">

# yt-stash

**Download YouTube videos and playlists from your terminal.**
Any quality, parallel downloads, members-only videos, subtitles, and a friendly arrow-key menu.

[![CI](https://github.com/ilkerkeklik01/yt-stash/actions/workflows/ci.yml/badge.svg)](https://github.com/ilkerkeklik01/yt-stash/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/yt-stash)](https://pypi.org/project/yt-stash/)
[![Python](https://img.shields.io/pypi/pyversions/yt-stash)](https://pypi.org/project/yt-stash/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/ilkerkeklik01/yt-stash/blob/main/LICENSE)

</div>

yt-stash is a cross-platform (Linux, macOS, Windows) command-line downloader for single videos, several
videos and whole playlists, including **members-only and private videos**. It is a thin, heavily tested
workflow layer on top of [yt-dlp](https://github.com/yt-dlp/yt-dlp), the best-maintained YouTube
extraction library, so it keeps working when YouTube changes.

## Features

- **Every quality**: detects all resolutions (144p … 8K, high frame rate, HDR) and lets you choose once
  for a whole batch. Defaults to **1080p**, or the highest available.
- **Videos and playlists**: one or many links, a text file of links, or every video of a playlist.
- **Parallel downloads**: several videos at once, plus parallel fragments per video.
- **Members-only, private and age-restricted videos** through your browser's signed-in session, a
  `cookies.txt` file, or cookies pasted for one run (never saved).
- **Audio only** (m4a, mp3, opus) and **subtitles** (save or embed, any language, auto-generated too).
- **Resume and skip**: interrupted downloads continue; files you already have are skipped; transient
  errors and rate limits are retried automatically.
- **Interactive or scriptable**: arrow-key menus with an explanation under every entry, or
  `--yes` plus flags for cron and CI, with documented exit codes.
- **English and Turkish** interface.

## Quickstart

```bash
# 1. Install (details for every system: docs/installation.md)
pipx install yt-stash

# 2. Open the interactive menu
yt-stash

# 3. Or download straight away
yt-stash video URL                    # asks for quality and folder
yt-stash video URL -q 720 -o ~/Videos                            # no questions
yt-stash video URL1 URL2 URL3 -j 3                               # three at once
yt-stash playlist "https://www.youtube.com/playlist?list=PL..."  # a whole playlist
yt-stash video URL -a mp3                                        # audio only
yt-stash video URL --subs en,tr --embed-subs                     # with subtitles
yt-stash video URL --cookies-from-browser firefox                # members-only video
```

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

## Installation

yt-stash needs Python 3.10+; install **ffmpeg** and **deno** too for full quality.

| System | Install |
|---|---|
| **macOS** | `brew install python pipx ffmpeg deno && pipx ensurepath`, then `pipx install yt-stash` |
| **Windows** (PowerShell) | `winget install Python.Python.3.13`, `winget install Gyan.FFmpeg`, `winget install DenoLand.Deno`, reopen PowerShell, `py -m pip install --user pipx`, `py -m pipx ensurepath`, reopen, then `pipx install yt-stash` |
| **Debian / Ubuntu** | `sudo apt install python3 pipx ffmpeg && pipx ensurepath`, install [deno](https://deno.com), then `pipx install yt-stash` |
| **Fedora / Arch / openSUSE / uv / pip / source** | see the [installation guide](https://github.com/ilkerkeklik01/yt-stash/blob/main/docs/installation.md) |

Check it: `yt-stash --version`. **If downloads suddenly fail, update first:** `pipx upgrade yt-stash`.

## Documentation

| Guide | What is in it |
|---|---|
| [Installation](https://github.com/ilkerkeklik01/yt-stash/blob/main/docs/installation.md) | Step by step for macOS, Windows and Linux; updating and uninstalling |
| [Using yt-stash](https://github.com/ilkerkeklik01/yt-stash/blob/main/docs/usage.md) | Every feature: menus, videos, playlists, quality, audio, subtitles, resume, language, scripting, all options, recipes |
| [Members-only videos](https://github.com/ilkerkeklik01/yt-stash/blob/main/docs/authentication.md) | Sign-in with browser cookies, a cookies file or pasted cookies |
| [Troubleshooting](https://github.com/ilkerkeklik01/yt-stash/blob/main/docs/troubleshooting.md) | Common problems and fixes |
| [Translating](https://github.com/ilkerkeklik01/yt-stash/blob/main/docs/translating.md) | Add or improve a language |
| [Architecture](https://github.com/ilkerkeklik01/yt-stash/blob/main/docs/ARCHITECTURE.md) | How the code is organised and why |
| [Changelog](https://github.com/ilkerkeklik01/yt-stash/blob/main/CHANGELOG.md) | What changed in each release |

Quick reference: `yt-stash --help`, `yt-stash video --help`, `yt-stash playlist --help`.

**Exit codes:** `0` everything downloaded or already present · `1` at least one video failed ·
`2` invalid usage · `130` interrupted with Ctrl+C.

## Getting help

- **Question or idea?** Open a [Discussion](https://github.com/ilkerkeklik01/yt-stash/discussions).
- **Found a bug?** Open an [issue](https://github.com/ilkerkeklik01/yt-stash/issues/new/choose); the form
  asks for the details that make it fixable.
- **Security problem?** Please don't open an issue; follow the
  [security policy](https://github.com/ilkerkeklik01/yt-stash/blob/main/SECURITY.md).

yt-stash is maintained by one volunteer in their spare time. Replies may take a few days; thank you
for your patience.

## Contributing

Contributions of every size are welcome: bug reports, documentation fixes, translations and code. Read
[CONTRIBUTING.md](https://github.com/ilkerkeklik01/yt-stash/blob/main/CONTRIBUTING.md) first; issues
labelled [`good first issue`](https://github.com/ilkerkeklik01/yt-stash/labels/good%20first%20issue) are
a good place to start. By taking part you agree to the
[Code of Conduct](https://github.com/ilkerkeklik01/yt-stash/blob/main/CODE_OF_CONDUCT.md).

```bash
git clone https://github.com/ilkerkeklik01/yt-stash.git && cd yt-stash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest && ruff check . && ruff format --check .
```

## Legal

yt-stash is released under the [MIT License](https://github.com/ilkerkeklik01/yt-stash/blob/main/LICENSE).
It is an independent project, not affiliated with or endorsed by YouTube or Google. Only download
content you have the right to download, and respect YouTube's Terms of Service and the creators'
rights. You are responsible for how you use this tool.

yt-stash does not remove DRM, bypass paywalls or circumvent access controls of its own; it drives yt-dlp, and
sign-in works only through cookies you already have. It collects no data and has no telemetry: the only
thing it stores is the language you choose, in a local settings file. Everything that goes over the network
is done by yt-dlp, to YouTube and its video servers.

yt-stash builds on [yt-dlp](https://github.com/yt-dlp/yt-dlp) (Unlicense), [rich](https://github.com/Textualize/rich)
(MIT), [questionary](https://github.com/tmbo/questionary) (MIT) and
[prompt_toolkit](https://github.com/prompt-toolkit/python-prompt-toolkit) (BSD-3-Clause). Thank you to their authors.
