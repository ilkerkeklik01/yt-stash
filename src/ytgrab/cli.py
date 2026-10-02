"""Command-line interface: argument parsing and wiring of the application."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from typing import Any

from rich.console import Console
from rich.markup import escape

from ytgrab import __version__
from ytgrab.app import App, RunOptions
from ytgrab.auth import AuthConfig
from ytgrab.downloader import DEFAULT_WORKERS, MAX_WORKERS
from ytgrab.environment import detect_environment
from ytgrab.errors import EXIT_INTERRUPTED, EXIT_USAGE, UsageError, YtGrabError
from ytgrab.formats import AUDIO_CODECS, parse_quality
from ytgrab.gateway import YtDlpClient, load_auth_cookies
from ytgrab.models import Mode, SubtitleOptions
from ytgrab.options import CONTAINERS, DEFAULT_CONTAINER
from ytgrab.paths import expand_path
from ytgrab.prompts import NonInteractivePrompter, RichPrompter, split_urls

EPILOG = """\
examples:
  ytgrab                                      interactive mode (asks for everything)
  ytgrab video https://youtu.be/dQw4w9WgXcQ   one video; asks for quality and folder
  ytgrab video URL1 URL2 -q 720 -o ~/Videos   several videos at 720p, no questions about them
  ytgrab playlist "https://www.youtube.com/playlist?list=PL..." -j 4
  ytgrab video URL --cookies-from-browser firefox     members-only / private videos
  ytgrab video URL --audio-only mp3
"""


def _jobs(value: str) -> int:
    try:
        jobs = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{value}' is not a number") from None
    if not 1 <= jobs <= MAX_WORKERS:
        raise argparse.ArgumentTypeError(f"must be between 1 and {MAX_WORKERS}")
    return jobs


def _add_common_options(parser: argparse.ArgumentParser, *, is_subcommand: bool) -> None:
    """Options accepted both before and after the subcommand.

    Real defaults live on the top-level parser only; on subcommands they are SUPPRESSed,
    otherwise argparse would overwrite a value given before the subcommand with the
    subcommand's default (``ytgrab -v video URL``).
    """

    def add(group: Any, *flags: str, **kwargs: Any) -> None:
        if is_subcommand:
            kwargs["default"] = argparse.SUPPRESS
        group.add_argument(*flags, **kwargs)

    out = parser.add_argument_group("output")
    add(out, "-o", "--output", metavar="DIR", help="target directory (asked if omitted)")
    add(
        out,
        "-q",
        "--quality",
        metavar="Q",
        help="resolution such as 2160, 1080, 720p, or 'best'/'worst' (asked if omitted; "
        "default 1080p, or the highest available if 1080p is not offered)",
    )
    add(
        out,
        "-a",
        "--audio-only",
        nargs="?",
        const="m4a",
        choices=AUDIO_CODECS,
        metavar="FORMAT",
        help=f"download audio only; FORMAT is one of {', '.join(AUDIO_CODECS)} (default: m4a)",
    )
    add(
        out,
        "--container",
        choices=CONTAINERS,
        default=DEFAULT_CONTAINER,
        help=f"video container (default: {DEFAULT_CONTAINER}; falls back to mkv if codecs require it)",
    )
    add(
        out,
        "--overwrite",
        action="store_true",
        help="download again even if the file already exists (e.g. to change quality)",
    )
    add(out, "--from-file", metavar="FILE", help="read URLs from a text file (one or more per line)")

    subs = parser.add_argument_group("subtitles")
    add(subs, "--subs", metavar="LANGS", help="comma-separated subtitle languages, e.g. 'en,tr' or 'all'")
    add(subs, "--auto-subs", action="store_true", help="also accept YouTube's auto-generated subtitles")
    add(
        subs,
        "--embed-subs",
        action="store_true",
        help="embed subtitles into the video file (requires ffmpeg)",
    )

    auth = parser.add_argument_group("authentication (members-only / private videos)")
    add(
        auth,
        "--cookies-from-browser",
        metavar="BROWSER[+KEYRING][:PROFILE][::CONTAINER]",
        help="use the signed-in session of a browser, e.g. 'firefox' or 'chrome:Profile 1'",
    )
    add(auth, "--cookies", metavar="FILE", help="Netscape-format cookies.txt file")

    run = parser.add_argument_group("execution")
    add(
        run,
        "-j",
        "--jobs",
        type=_jobs,
        default=DEFAULT_WORKERS,
        help=f"parallel downloads, 1-{MAX_WORKERS} (default: {DEFAULT_WORKERS})",
    )
    add(
        run,
        "-y",
        "--yes",
        action="store_true",
        help="never ask questions; use flags or defaults (implied when not in a terminal)",
    )
    add(run, "--list-qualities", action="store_true", help="only show available qualities, do not download")
    add(run, "--ffmpeg-location", metavar="PATH", help="ffmpeg binary or its folder")
    add(run, "-v", "--verbose", action="store_true", help="show yt-dlp debug output")


def build_parser() -> argparse.ArgumentParser:
    formatter = argparse.RawDescriptionHelpFormatter
    parser = argparse.ArgumentParser(
        prog="ytgrab",
        description="Download YouTube videos and playlists in any available quality.",
        epilog=EPILOG,
        formatter_class=formatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.set_defaults(mode=None, urls=[])
    _add_common_options(parser, is_subcommand=False)

    commands = parser.add_subparsers(dest="mode", metavar="{video,playlist}")
    video = commands.add_parser(
        "video", help="download one or more videos", epilog=EPILOG, formatter_class=formatter
    )
    video.add_argument("urls", nargs="*", metavar="URL", help="video URLs or 11-character ids")
    _add_common_options(video, is_subcommand=True)

    playlist = commands.add_parser(
        "playlist", help="download every video of a playlist", epilog=EPILOG, formatter_class=formatter
    )
    playlist.add_argument("urls", nargs="*", metavar="URL", help="playlist URL")
    _add_common_options(playlist, is_subcommand=True)
    return parser


def _read_url_file(raw_path: str) -> list[str]:
    path = expand_path(raw_path)
    try:
        # utf-8-sig drops the byte-order mark that Windows Notepad writes.
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        reason = exc.strerror if isinstance(exc, OSError) else "not a UTF-8 text file"
        raise UsageError(f"Cannot read URL file '{path}': {reason or exc}") from exc
    return [url for line in lines if not line.lstrip().startswith("#") for url in split_urls(line)]


def options_from_args(args: argparse.Namespace) -> RunOptions:
    """Validate parsed arguments and turn them into :class:`RunOptions`."""
    urls = list(args.urls)
    if args.from_file:
        urls.extend(_read_url_file(args.from_file))

    if args.audio_only and args.quality:
        raise UsageError("--audio-only and --quality cannot be combined.")
    languages = tuple(lang.strip() for lang in (args.subs or "").split(",") if lang.strip())
    if (args.auto_subs or args.embed_subs) and not languages:
        raise UsageError("--auto-subs/--embed-subs need --subs LANGS (e.g. --subs en).")

    return RunOptions(
        mode=Mode(args.mode) if args.mode else None,
        urls=tuple(urls),
        output_dir=expand_path(args.output) if args.output else None,
        quality=parse_quality(args.quality) if args.quality else None,
        audio_codec=args.audio_only,
        container=args.container,
        subtitles=SubtitleOptions(languages, args.auto_subs, args.embed_subs),
        auth=AuthConfig.from_options(args.cookies_from_browser, args.cookies),
        jobs=args.jobs,
        overwrite=args.overwrite,
        list_qualities=args.list_qualities,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point of the ``ytgrab`` command. Returns the process exit code."""
    args = build_parser().parse_args(argv)
    console = Console(highlight=False)
    interactive = sys.stdin.isatty() and not args.yes

    def on_debug(message: str) -> None:
        if args.verbose:
            console.print(f"[dim]{escape(message)}")

    try:
        options = options_from_args(args)
        environment = detect_environment(expand_path(args.ffmpeg_location) if args.ffmpeg_location else None)
        app = App(
            options,
            prompter=RichPrompter(console) if interactive else NonInteractivePrompter(),
            console=console,
            environment=environment,
            client_factory=lambda cookies: YtDlpClient(environment, cookies, on_debug),
            cookie_loader=lambda auth: load_auth_cookies(auth, on_debug),
            interactive=interactive,
        )
        return app.run()
    except YtGrabError as error:
        console.print(f"[red]Error:[/] {escape(str(error))}")
        return error.exit_code
    except EOFError:  # stdin closed while a question was asked
        console.print("\n[red]Error:[/] input ended unexpectedly.")
        return EXIT_USAGE
    except KeyboardInterrupt:
        # Reaching here means the user insisted (or interrupted outside a download).
        # Worker threads may still be blocked in network calls; a normal exit would wait
        # for them, so leave immediately. Partial downloads are kept for resuming.
        console.print("\n[yellow]Interrupted.")
        sys.stdout.flush()
        os._exit(EXIT_INTERRUPTED)


if __name__ == "__main__":
    sys.exit(main())
