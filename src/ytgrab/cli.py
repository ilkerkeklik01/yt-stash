"""Command-line interface: argument parsing and wiring of the application."""

from __future__ import annotations

import argparse
import functools
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markup import escape

from ytgrab import __version__
from ytgrab.app import App, RunOptions
from ytgrab.auth import AuthConfig
from ytgrab.downloader import DEFAULT_WORKERS, MAX_WORKERS
from ytgrab.environment import detect_environment
from ytgrab.errors import EXIT_INTERRUPTED, EXIT_OK, EXIT_USAGE, UsageError, YtGrabError
from ytgrab.formats import AUDIO_CODECS, parse_quality
from ytgrab.gateway import YtDlpClient, load_auth_cookies
from ytgrab.i18n import LANGUAGES, resolve_language, set_language, system_language, t
from ytgrab.models import Mode, SubtitleOptions
from ytgrab.options import CONTAINERS, DEFAULT_CONTAINER, split_languages
from ytgrab.paths import expand_path
from ytgrab.prompts import GoBack, NonInteractivePrompter, TerminalPrompter
from ytgrab.session import Session
from ytgrab.settings import config_path, load_settings
from ytgrab.urls import read_url_file

# (command, catalog key of its explanation or None); commands are never translated.
_EXAMPLES = (
    ("ytgrab", "cli.example.menu"),
    ("ytgrab video https://youtu.be/dQw4w9WgXcQ", "cli.example.one_video"),
    ("ytgrab video URL1 URL2 -q 720 -o ~/Videos", "cli.example.several"),
    ('ytgrab playlist "https://www.youtube.com/playlist?list=PL..." -j 4', None),
    ("ytgrab video URL --cookies-from-browser firefox", "cli.example.members"),
    ("ytgrab video URL --audio-only mp3", None),
    ("ytgrab --lang tr", "cli.example.language"),
)


def _epilog() -> str:
    lines = [t("cli.examples")]
    for command, key in _EXAMPLES:
        lines.append(f"  {command:<41}   {t(key)}" if key else f"  {command}")
    return "\n".join(lines) + "\n"


def _jobs(value: str) -> int:
    try:
        jobs = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(t("cli.jobs_not_number", value=value)) from None
    if not 1 <= jobs <= MAX_WORKERS:
        raise argparse.ArgumentTypeError(t("cli.jobs_range", max=MAX_WORKERS))
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

    out = parser.add_argument_group(t("cli.group.output"))
    add(out, "-o", "--output", metavar="DIR", help=t("cli.help.output"))
    add(out, "-q", "--quality", metavar="Q", help=t("cli.help.quality"))
    add(
        out,
        "-a",
        "--audio-only",
        nargs="?",
        const="m4a",
        choices=AUDIO_CODECS,
        metavar="FORMAT",
        help=t("cli.help.audio_only", codecs=", ".join(AUDIO_CODECS)),
    )
    add(
        out,
        "--container",
        choices=CONTAINERS,
        default=DEFAULT_CONTAINER,
        help=t("cli.help.container", default=DEFAULT_CONTAINER),
    )
    add(out, "--overwrite", action="store_true", help=t("cli.help.overwrite"))
    add(out, "--from-file", metavar="FILE", help=t("cli.help.from_file"))

    subs = parser.add_argument_group(t("cli.group.subtitles"))
    add(subs, "--subs", metavar="LANGS", help=t("cli.help.subs"))
    add(subs, "--auto-subs", action="store_true", help=t("cli.help.auto_subs"))
    add(subs, "--embed-subs", action="store_true", help=t("cli.help.embed_subs"))

    auth = parser.add_argument_group(t("cli.group.auth"))
    add(
        auth,
        "--cookies-from-browser",
        metavar="BROWSER[+KEYRING][:PROFILE][::CONTAINER]",
        help=t("cli.help.cookies_from_browser"),
    )
    add(auth, "--cookies", metavar="FILE", help=t("cli.help.cookies"))

    run = parser.add_argument_group(t("cli.group.execution"))
    add(
        run,
        "-j",
        "--jobs",
        type=_jobs,
        default=DEFAULT_WORKERS,
        help=t("cli.help.jobs", max=MAX_WORKERS, default=DEFAULT_WORKERS),
    )
    add(run, "-y", "--yes", action="store_true", help=t("cli.help.yes"))
    add(run, "--list-qualities", action="store_true", help=t("cli.help.list_qualities"))
    add(run, "--ffmpeg-location", metavar="PATH", help=t("cli.help.ffmpeg_location"))
    add(run, "--lang", choices=list(LANGUAGES), help=t("cli.help.lang", languages=", ".join(LANGUAGES)))
    add(run, "-v", "--verbose", action="store_true", help=t("cli.help.verbose"))


def build_parser() -> argparse.ArgumentParser:
    """The argument parser, with help texts in the current language."""
    formatter = argparse.RawDescriptionHelpFormatter
    epilog = _epilog()
    parser = argparse.ArgumentParser(
        prog="ytgrab",
        description=t("cli.description"),
        epilog=epilog,
        formatter_class=formatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.set_defaults(mode=None, urls=[])
    _add_common_options(parser, is_subcommand=False)

    commands = parser.add_subparsers(dest="mode", metavar="{video,playlist}")
    video = commands.add_parser("video", help=t("cli.help.video"), epilog=epilog, formatter_class=formatter)
    video.add_argument("urls", nargs="*", metavar="URL", help=t("cli.help.video_urls"))
    _add_common_options(video, is_subcommand=True)

    playlist = commands.add_parser(
        "playlist", help=t("cli.help.playlist"), epilog=epilog, formatter_class=formatter
    )
    playlist.add_argument("urls", nargs="*", metavar="URL", help=t("cli.help.playlist_url"))
    _add_common_options(playlist, is_subcommand=True)
    return parser


def options_from_args(args: argparse.Namespace) -> RunOptions:
    """Validate parsed arguments and turn them into :class:`RunOptions`."""
    urls = list(args.urls)
    if args.from_file:
        urls.extend(read_url_file(args.from_file))

    if args.audio_only and args.quality:
        raise UsageError(t("cli.audio_and_quality"))
    languages = split_languages(args.subs or "")
    if (args.auto_subs or args.embed_subs) and not languages:
        raise UsageError(t("cli.subs_needed"))

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


def _choose_language(argv: Sequence[str] | None, settings_file: Path) -> None:
    """Set the language before any text is built, including the ``--help`` text.

    Priority: ``--lang``, ``YTGRAB_LANG``, the choice saved from the main menu, the system
    language, English. An invalid ``--lang`` is ignored here; the real parser reports it.
    """
    early = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    early.add_argument("--lang", nargs="?")  # a missing value is reported by the real parser
    flag = early.parse_known_args(argv)[0].lang
    saved = load_settings(settings_file).get("language")
    set_language(
        resolve_language(
            flag,
            os.environ.get("YTGRAB_LANG"),
            saved if isinstance(saved, str) else None,
            system_language(),
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point of the ``ytgrab`` command. Returns the process exit code."""
    settings_file = config_path()
    _choose_language(argv, settings_file)
    parser = build_parser()
    args = parser.parse_args(argv)
    console = Console(highlight=False)
    # Arrow-key menus need a terminal on both ends; otherwise behave like --yes.
    interactive = sys.stdin.isatty() and sys.stdout.isatty() and not args.yes

    def on_debug(message: str) -> None:
        if args.verbose:
            console.print(f"[dim]{escape(message)}")

    try:
        options = options_from_args(args)
        environment = detect_environment(expand_path(args.ffmpeg_location) if args.ffmpeg_location else None)
        prompter = TerminalPrompter(console) if interactive else NonInteractivePrompter()
        # Cached per sign-in, so later runs of a session don't hit the browser (and keychain) again.
        cookie_loader = functools.cache(functools.partial(load_auth_cookies, on_debug=on_debug))

        def make_app(run_options: RunOptions, *, check_environment: bool = True) -> App:
            return App(
                run_options,
                prompter=prompter,
                console=console,
                environment=environment,
                client_factory=lambda cookies: YtDlpClient(environment, cookies, on_debug),
                cookie_loader=cookie_loader,
                interactive=interactive,
                check_environment=check_environment,
            )

        if isinstance(prompter, TerminalPrompter) and options.mode is None and not options.urls:
            session = Session(
                options,
                prompter=prompter,
                console=console,
                environment=environment,
                # The session shows environment warnings once, not before every download.
                app_factory=lambda run_options: make_app(run_options, check_environment=False),
                help_text=lambda: build_parser().format_help(),  # in the language chosen by then
                settings_file=settings_file,
            )
            return session.run()
        return make_app(options).run()
    except GoBack:  # Esc with nothing to go back to
        console.print(t("cancelled"))
        return EXIT_OK
    except YtGrabError as error:
        console.print(t("cli.error", message=escape(str(error))))
        return error.exit_code
    except EOFError:  # stdin closed while a question was asked
        console.print("\n" + t("cli.error", message=t("cli.input_ended")))
        return EXIT_USAGE
    except KeyboardInterrupt:
        # Reaching here means the user insisted (or interrupted outside a download).
        # Worker threads may still be blocked in network calls; a normal exit would wait
        # for them, so leave immediately. Partial downloads are kept for resuming.
        console.print(f"\n[yellow]{t('cli.interrupted')}")
        sys.stdout.flush()
        os._exit(EXIT_INTERRUPTED)


if __name__ == "__main__":
    sys.exit(main())
