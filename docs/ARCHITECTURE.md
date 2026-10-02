# Architecture

ytgrab is a thin, well-tested layer of workflow and UX around the yt-dlp library.
Pure decision logic is separated from I/O so that almost everything can be tested
offline with fakes.

```
cli.py ──► app.py ──────────────────────────────────────────────┐
 (argparse)  (workflow)                                          │
              │ uses                                             │
              ├─ prompts.py   Prompter protocol (Rich / NonInteractive)
              ├─ progress.py  live progress bars (rich)          │
              ├─ probe.py     parallel metadata fetching         │
              ├─ downloader.py parallel downloads, cancel        │
              │       ├─ retry.py        back-off for transient errors
              │       └─ concurrency.py  Ctrl+C-safe thread pool │
              └─ gateway.py   MediaClient protocol + YtDlpClient ◄┘  ← the only yt-dlp API caller
pure logic:  urls.py · formats.py · options.py · errors.py · paths.py · auth.py · models.py
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
| `prompts.py` / `progress.py` | Terminal UI. |
| `app.py` | Orchestrates the workflow and the "ask for sign-in and retry" recovery. |
| `cli.py` | Argument parsing and dependency wiring. |

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

**Errors never abort the batch.** Every per-video problem becomes a `ProbeFailure` or a
failed `JobResult`; the summary lists them and the exit code becomes 1.

## Testing

- `tests/conftest.py` provides `FakeClient` (an in-memory `MediaClient`) and a
  `ScriptedPrompter`, so the whole workflow in `app.py` is tested without network or TTY.
- `test_gateway.py` replaces `yt_dlp.YoutubeDL` with a stub to test parameter wiring,
  hooks, cancellation and error translation; cookie loading uses real yt-dlp offline.
- `tests/test_network.py` (marker `network`, excluded by default) downloads a real
  19-second video end to end.
