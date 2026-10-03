# Architecture

ytgrab is a thin, well-tested layer of workflow and UX around the yt-dlp library.
Pure decision logic is separated from I/O so that almost everything can be tested
offline with fakes.

```
cli.py ──► session.py ──► app.py ─────────────────────────────────┐
 (argparse)  (main menu)    (workflow)                           │
              │ uses                                             │
              ├─ prompts.py   Prompter protocol (Terminal / NonInteractive)
              ├─ progress.py  live progress bars (rich)          │
              ├─ probe.py     parallel metadata fetching         │
              ├─ downloader.py parallel downloads, cancel        │
              │       ├─ retry.py        back-off for transient errors
              │       └─ concurrency.py  Ctrl+C-safe thread pool │
              └─ gateway.py   MediaClient protocol + YtDlpClient ◄┘  ← the only yt-dlp API caller
pure logic:  urls.py · formats.py · options.py · commandline.py · errors.py · paths.py · auth.py · models.py
text:        i18n/ (en.py, tr.py catalogs) · settings.py (saved language)
```

## Modules

| Module | Responsibility |
|---|---|
| `models.py` | Immutable data types (`VideoInfo`, `Resolution`, `QualityOption`, `Selection`, …). |
| `urls.py` | Validates every YouTube URL form, extracts ids, returns canonical de-duplicated URLs. |
| `formats.py` | Turns yt-dlp format lists into resolutions, builds the batch-wide quality menu, default rule (1080p → max), `--quality` parsing. |
| `options.py` | Translates `DownloadSettings` into yt-dlp parameter dicts (format sort, container, subtitles, overwrite policy, file names). |
| `errors.py` | Exception hierarchy; classifies yt-dlp messages into `ErrorKind` (auth, unavailable, rate-limited, network, …). |
| `auth.py` | Browser/cookies-file authentication settings and validation. |
| `paths.py` | Target directory checks (creatable, writable) and portable folder names. |
| `environment.py` | Detects ffmpeg and JavaScript runtimes. |
| `gateway.py` | `MediaClient` protocol and the yt-dlp implementation: extraction, downloads, progress hooks, cancellation, cookie loading. |
| `probe.py` | Fetches metadata of many videos concurrently; collects failures instead of raising. |
| `retry.py` | `RetryPolicy` and `call_with_retry`, shared by probing and downloading. |
| `concurrency.py` | `map_interruptible`: thread pool that stays responsive to Ctrl+C on every OS. |
| `downloader.py` | `DownloadManager`: concurrent jobs, retries, cancellation, results. |
| `commandline.py` | Renders the `ytgrab` command that repeats an interactive run without questions. |
| `prompts.py` | `Prompter` protocol; `TerminalPrompter` (arrow-key menus via questionary, every entry explained) and `NonInteractivePrompter`. |
| `browse.py` | Folder listings for the arrow-key file/folder browser (hidden entries skipped, unreadable folders reported). |
| `viewer.py` | Full-screen, scrollable page (alternate screen) for the setup check and command-line help. |
| `progress.py` | Live progress bars. |
| `app.py` | Orchestrates one run: probe, choose, review screen (`DownloadPlan`), download, "ask for sign-in and retry" recovery. |
| `session.py` | Main menu shown by a bare `ytgrab`: runs one `App` per choice, keeps the sign-in between runs. |
| `cli.py` | Argument parsing, choice of language and dependency wiring. |
| `i18n/` | Message catalogs (`en.py`, `tr.py`), `t()`/`tn()` lookup and the choice of language. |
| `settings.py` | Settings kept between runs (the language chosen in the menu) as JSON in the OS config folder. |

## Key decisions

**Quality selection with `res:<height>` sorting.** Instead of a strict filter like
`height=1080` (which fails for videos without that height), ytgrab passes
`format_sort=["res:1080", "fps", …]`. yt-dlp then prefers the largest resolution ≤ 1080,
falling back to the smallest above it. One choice therefore works for a whole playlist.

**Short side as the "p" value.** Resolutions are keyed by `min(width, height)`, which
matches how YouTube labels vertical videos and how yt-dlp's `res` sort field works.

**One yt-dlp instance per thread / per download.** `YoutubeDL` is not thread-safe.
Probing reuses a thread-local instance; each download creates its own instance (it
carries per-download hooks).

**Cookies are read once.** Browser cookie extraction can be slow and trigger OS keychain
prompts. `load_auth_cookies` reads them once, serialises them, and every yt-dlp
instance receives its own in-memory copy (`io.StringIO`). This also guarantees that
yt-dlp never writes back to the user's `cookies.txt`.

**Cancellation.** The main thread waits on futures with a short timeout so Ctrl+C is
delivered promptly on every OS (including Windows). On interrupt a shared `Event` is set;
download progress hooks raise yt-dlp's `DownloadCancelled` at their next tick, queued
jobs are cancelled, and partial files remain for resuming. Jobs that failed because the
same Ctrl+C killed their ffmpeg child are reported as cancelled, not failed. Probing does
not wait for in-flight requests, and a second Ctrl+C exits immediately.

**Retries.** yt-dlp already retries HTTP requests and fragments. On top of that, probing
and downloading retry a whole video for transient errors (network, HTTP 429) with
exponential back-off (longer for rate limits), interruptible by Ctrl+C. Permanent errors
fail fast.

**Skipping existing files instead of a download archive.** yt-dlp skips a download whose
final file already exists and then emits no "downloading" progress; the gateway reports
that as `already_present`. Unlike an id-based archive this naturally distinguishes audio
from video downloads and re-downloads deleted files. `final_ext` is set for audio
extraction so converted files (e.g. `.mp3`) are recognised.

**yt-dlp boundary.** Only `gateway.py` calls yt-dlp's API. `auth.py` additionally imports
yt-dlp's lists of supported browsers/keyrings so validation never drifts from yt-dlp.

**Prompters ask, the app decides.** The review screen loop lives in `App`, which owns
validation (writable folder, playlist subfolder, whether subtitles can be embedded).
Prompter methods only ask one question and return the answer, so the whole workflow is
tested with `ScriptedPrompter`, and `TerminalPrompter` is tested by sending real key
presses through prompt_toolkit's pipe input.

**Esc goes back.** `TerminalPrompter` binds Esc on every question except the main menu;
the question then raises `GoBack`. Whoever asked decides where "back" leads: a
multi-step question (sign-in, subtitles) returns to its first step, the review screen
keeps the old value, the folder question returns to the quality question, and anything
else leaves `App.run()` so the session shows the main menu (or the CLI cancels). Menus need a terminal on stdin *and*
stdout; otherwise ytgrab behaves as with `--yes`.

**All user-visible text comes from the catalogs.** Code calls `t("key", **values)` (or
`tn` for counts) when it shows text, never at import time, so choosing a language in the
main menu redraws everything in it at once. Each sentence is one template: Turkish
attaches suffixes by vowel harmony and orders words differently, so text is never built
from translated pieces, and a value is never followed by a suffix (`Kullanılıyor: {auth}`).
What must stay English stays out of the catalogs: yt-dlp's messages and the patterns that
classify them (`ErrorKind` values are English; `ErrorKind.label` is the translation),
flags, quality keywords, folder names on disk and command examples. Tests check that every
catalog has the same keys, placeholders and markup, and that every key exists and is used.

**The language is process-wide state.** Like gettext, `i18n` keeps the current language in
one module variable instead of passing a translator to every object. It is written only on
the main thread (at start-up, and from the main menu while nothing downloads) and only read
by worker threads, and it is the only hidden input of the pure modules (their messages). `cli.main` chooses it before building the argument parser so `--help`
is translated: `--lang`, `YTGRAB_LANG`, the saved choice, the system language, English.
argparse's own words (`usage:`, `options:`) and questionary's `Description:` stay English.

**Errors never abort the batch.** Every per-video problem becomes a `ProbeFailure` or a
failed `JobResult`; the summary lists them and the exit code becomes 1.

## Testing

- `tests/conftest.py` provides `FakeClient` (an in-memory `MediaClient`) and a
  `ScriptedPrompter`, so the whole workflow in `app.py` is tested without network or TTY.
  An autouse fixture starts every test in English with no saved settings or locale.
- `test_gateway.py` replaces `yt_dlp.YoutubeDL` with a stub to test parameter wiring,
  hooks, cancellation and error translation; cookie loading uses real yt-dlp offline.
- `tests/test_network.py` (marker `network`, excluded by default) downloads a real
  19-second video end to end.
