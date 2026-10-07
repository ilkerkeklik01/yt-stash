# Troubleshooting

First, two things that fix most problems:

1. **Update.** YouTube changes often. `pipx upgrade yt-stash` (or `uv tool upgrade yt-stash`,
   `pip install -U yt-stash`) also updates yt-dlp.
2. **Run Check setup** in the main menu (`yt-stash`, then *Check setup*) to see whether ffmpeg and a
   JavaScript runtime are found.

| Symptom | Cause and fix |
|---|---|
| Only 360p or lower is offered | Install **ffmpeg** and **deno** ([installation](installation.md)), then check with *Check setup*. |
| "Sign in to confirm you're not a bot" | Use `--cookies-from-browser firefox`, lower the parallel jobs (`-j 1`), or wait a while. |
| "rate limited" / HTTP 429 | yt-stash retries with increasing back-off. Use fewer parallel jobs (`-j 1`) or try later. |
| "Could not load cookies" | Close the browser (Chrome/Edge on Windows), choose the right profile (`chrome:Profile 1`), use Firefox, or pass `--cookies FILE`. See [Authentication](authentication.md#platform-notes). |
| A members-only video still fails with cookies | The signed-in account must have an active membership of that channel, and the cookies must be recent. |
| "Video unavailable", "Private video" | The video was removed or is private. In a playlist, yt-stash reports it, skips it and downloads the rest (exit code 1). |
| Output is `.mkv`, not `.mp4` | Resolutions above 1080p use VP9/AV1, which mp4 can't always hold. Use `--container mkv` to make this explicit. |
| mp3, merging or `--embed-subs` fails | ffmpeg is missing. Install it, or point to it with `--ffmpeg-location PATH`. |
| "Already downloaded" but you want it again | Use `--overwrite`, or delete the file. |
| Download stopped halfway | Run the same command again; partial `.part` files are resumed. |
| Garbled menus or boxes | Use a modern terminal with UTF-8: Windows Terminal, iTerm2, GNOME Terminal, and so on. |
| `yt-stash: command not found` | See [Troubleshooting the installation](installation.md#troubleshooting-the-installation). |

## Still stuck?

1. Run the failing command again with `-v` for yt-dlp's debug output.
2. Search the [existing issues](https://github.com/ilkerkeklik01/yt-stash/issues?q=is%3Aissue).
3. Ask in [Discussions](https://github.com/ilkerkeklik01/yt-stash/discussions) for help using
   yt-stash, or open a [bug report](https://github.com/ilkerkeklik01/yt-stash/issues/new/choose) with
   your version (`yt-stash --version`), operating system, the command and the `-v` output.
   **Remove cookies and personal links from anything you post.**

If the same error also happens with plain yt-dlp (`yt-dlp URL`), it is a yt-dlp or YouTube issue; check
[yt-dlp's issues](https://github.com/yt-dlp/yt-dlp/issues).
