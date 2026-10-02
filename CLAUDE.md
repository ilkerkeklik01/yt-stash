# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

ytgrab is a cross-platform (Linux/macOS/Windows) Python CLI that downloads YouTube videos and playlists. It is a thin, heavily tested workflow/UX layer over the yt-dlp library, with `rich` for progress and `questionary`/prompt_toolkit for arrow-key menus. Entry point: `ytgrab = ytgrab.cli:main` (also `python -m ytgrab`).

## Commands

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest                                   # offline suite (network tests excluded via addopts)
pytest tests/test_formats.py             # one file
pytest tests/test_app.py::test_name      # one test
pytest -k "review and not subtitles"     # by keyword
pytest -m network                        # real YouTube download end to end (needs internet)
pytest --cov --cov-report=term-missing   # coverage, as CI runs it

ruff check . && ruff format --check .    # lint + format check (line length 110)
ruff format .                            # apply formatting
```

CI (`.github/workflows/ci.yml`) runs ruff on 3.12, and pytest on Ubuntu/macOS/Windows × Python 3.10/3.13, plus a smoke test `ytgrab --version && ytgrab video --help`. Code must stay compatible with Python 3.10 and Windows.

The version lives in `src/ytgrab/__init__.py` (read by hatchling).

## Architecture

`docs/ARCHITECTURE.md` is the authoritative design doc (module table and key decisions) — read it before non-trivial changes and keep it updated when behavior or module responsibilities change. The README documents user-facing behavior, options and exit codes; keep it in sync too.

Flow: `cli.py` (argparse + dependency wiring) → `session.py` (main menu for bare `ytgrab`, one `App` per choice, keeps sign-in between runs) → `app.py` (one run: probe → choose quality/folder → review screen → download → "sign in and retry" recovery).

Invariants that span multiple files:

- **Only `gateway.py` calls the yt-dlp API** (`MediaClient` protocol, `YtDlpClient` implementation). `auth.py` may import yt-dlp's browser/keyring lists for validation only. Everything else talks to `MediaClient`.
- **Pure logic is separated from I/O**: `urls`, `formats`, `options`, `commandline`, `errors`, `paths`, `auth`, `models` do no I/O and have no side effects; their only hidden input is the current language, read through `i18n.t()` for messages. They are tested directly.
- **`YoutubeDL` is not thread-safe**: probing uses a thread-local instance; each download creates its own. Cookies are loaded once (`load_auth_cookies`) and each instance gets an in-memory `io.StringIO` copy — never let yt-dlp write back to the user's cookies file.
- **Quality uses `format_sort=["res:<h>", ...]`**, not a strict height filter, so one choice works across a whole playlist. Resolutions are keyed by the short side, `min(width, height)`.
- **Prompters ask, the app decides**: `Prompter` methods (`prompts.py`) ask exactly one question and return the answer; validation and the review-screen loop live in `App`. `TerminalPrompter` raises `GoBack` on Esc, and the caller decides where "back" leads. `NonInteractivePrompter` is used with `--yes` or when stdin/stdout isn't a TTY.
- **All user-visible text goes through `i18n.t()`/`tn()`** with keys in both `i18n/en.py` and `i18n/tr.py` (same keys, placeholders and markup; `tests/test_i18n.py` enforces it). Call `t()` when the text is shown, never in module-level constants. Write whole-sentence templates and never attach a Turkish suffix to a placeholder. yt-dlp messages, `errors._PATTERNS`, `ErrorKind` values, flags and commands stay English. The current language is a module global written only on the main thread.
- **Errors never abort the batch**: per-video problems become `ProbeFailure` / failed `JobResult`; `errors.py` classifies yt-dlp messages into `ErrorKind`. Exit codes: 0 ok, 1 any video failed, 2 usage error, 130 Ctrl+C.
- **Cancellation**: `concurrency.map_interruptible` waits on futures with short timeouts so Ctrl+C works on Windows; a shared `Event` makes progress hooks raise `DownloadCancelled`; partial files are kept for resume. Transient errors (network, HTTP 429) are retried via `retry.py` for both probing and downloading.
- **Skip-existing** relies on yt-dlp skipping an existing final file; the gateway reports that as `already_present` (no download archive). `final_ext` must be set for audio extraction.

## Testing

- No default test touches the network. `tests/conftest.py` provides `FakeClient` (in-memory `MediaClient`), `ScriptedPrompter`, and yt-dlp-shaped dict builders (`fmt`, `video_info`). Test workflow changes in `app.py`/`session.py` through these fakes.
- An autouse fixture in `conftest.py` starts every test in English and isolates locale variables and the settings file; switch with `i18n.set_language("tr")` to test Turkish output.
- `test_gateway.py` stubs `yt_dlp.YoutubeDL` to test parameter wiring, hooks, cancellation and error translation.
- `test_ui.py` drives `TerminalPrompter` with real key presses via prompt_toolkit pipe input.
- Network tests must be marked `@pytest.mark.network` (`--strict-markers` is on).
