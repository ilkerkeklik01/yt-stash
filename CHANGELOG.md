# Changelog

All notable changes to yt-stash are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). For a command-line tool, the
public interface that SemVer applies to is: command names, flags and their meaning, exit codes, and
the environment variables and settings file described in the documentation.

## [Unreleased]

### Changed

- Examples in the documentation and help text use a `URL` placeholder instead of a real video.

## [1.0.0] - 2026-10-08

First public release.

### Added

- Interactive main menu (`yt-stash` without arguments) with arrow-key navigation, a description
  under every entry, Esc to go back, and a built-in setup check.
- `video` mode for one or more videos and `playlist` mode for whole playlists, with links read
  from arguments or from a text file (`--from-file`).
- Quality selection across a whole batch: every available resolution from 144p to 8K is
  detected, the default is 1080p (or the highest available), and `-q` accepts `2160`, `720p`,
  `best` and `worst`.
- Audio-only downloads (`-a`: m4a, mp3, opus) and the video container choice (`--container`).
- Subtitles: download, auto-generated captions and embedding (`--subs`, `--auto-subs`,
  `--embed-subs`).
- Members-only, private and age-restricted videos through a browser's signed-in session
  (`--cookies-from-browser`), a `cookies.txt` file (`--cookies`), or cookies pasted for one run
  (`--paste-cookies`); an interactive "sign in and retry" recovery.
- Parallel downloads (`-j`), resume of interrupted downloads, skipping of files that already exist
  (`--overwrite` to override), and automatic retries with back-off for network errors and HTTP 429.
- Scripting support: `--yes`, automatic non-interactive mode without a terminal, a command that
  repeats an interactive run, and the exit codes 0, 1, 2 and 130.
- English and Turkish interface (`--lang`, `YT_STASH_LANG`, saved choice, system language).
- Packaging for PyPI, an MIT license, a code of conduct, a security policy, contribution guidelines,
  issue forms, and installation guides for macOS, Windows and Linux.

[Unreleased]: https://github.com/ilkerkeklik01/yt-stash/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/ilkerkeklik01/yt-stash/releases/tag/v1.0.0
