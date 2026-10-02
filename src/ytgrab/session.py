"""Interactive main menu: several downloads in one session, without knowing any flags."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import replace
from importlib.metadata import version

from rich.console import Console
from rich.markup import escape
from rich.table import Table
from rich.text import Text

from ytgrab import __version__
from ytgrab.app import App, RunOptions, environment_warnings
from ytgrab.auth import AuthConfig
from ytgrab.environment import Environment
from ytgrab.errors import EXIT_INTERRUPTED, EXIT_OK, YtGrabError
from ytgrab.models import Mode
from ytgrab.prompts import GoBack, MenuAction, SessionPrompter

AppFactory = Callable[[RunOptions], App]

SIGN_IN_REASON = (
    "Members-only, private and age-restricted videos need your signed-in YouTube account. "
    "ytgrab reads the session cookies of your browser or of a cookies.txt file and keeps "
    "them in memory only; nothing is saved."
)

_LINUX_HINTS = {
    "ffmpeg": "sudo apt install ffmpeg  (Fedora: sudo dnf install ffmpeg)",
    "deno": "curl -fsSL https://deno.land/install.sh | sh",
}
INSTALL_HINTS = {
    "darwin": {"ffmpeg": "brew install ffmpeg", "deno": "brew install deno"},
    "win32": {"ffmpeg": "winget install Gyan.FFmpeg", "deno": "winget install DenoLand.Deno"},
}


def setup_table(environment: Environment, platform: str = sys.platform) -> Table:
    """Which external programs were found, what they are for and how to install missing ones."""
    hints = INSTALL_HINTS.get(platform, _LINUX_HINTS)
    table = Table(show_header=False, show_edge=False, box=None, padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_column()

    if environment.ffmpeg_available:
        table.add_row(
            "ffmpeg", "[green]✔ found", "[dim]Merges HD video with audio, converts audio, embeds subtitles."
        )
    else:
        table.add_row("ffmpeg", "[red]✘ missing", f"Install: [b]{hints['ffmpeg']}")
    runtimes = ", ".join(environment.js_runtimes)
    if runtimes:
        table.add_row("JavaScript", f"[green]✔ {runtimes}", "[dim]Unlocks most of YouTube's formats.")
    else:
        table.add_row("JavaScript", "[red]✘ missing", f"Install: [b]{hints['deno']}")
    table.add_row(
        "yt-dlp",
        version("yt-dlp"),
        "[dim]If downloads suddenly fail, update it: [/]pipx upgrade ytgrab[dim] or [/]pip install -U yt-dlp",
    )
    return table


class Session:
    """Shows the main menu, runs an :class:`App` per choice and keeps the sign-in between runs."""

    def __init__(
        self,
        base_options: RunOptions,
        *,
        prompter: SessionPrompter,
        console: Console,
        environment: Environment,
        app_factory: AppFactory,
        help_text: str,
    ) -> None:
        self._base = base_options
        self._prompter = prompter
        self._console = console
        self._env = environment
        self._app_factory = app_factory
        self._help_text = help_text
        self._auth = base_options.auth

    def run(self) -> int:
        """Loop until the user quits. Returns the exit code of the last download."""
        self._console.print(f"[b]ytgrab[/] {__version__}  [dim]Download YouTube videos and playlists")
        for warning in environment_warnings(self._env):
            self._console.print(warning)

        exit_code = EXIT_OK
        action: MenuAction | None = None
        while True:
            self._console.print()
            try:
                action = self._prompter.ask_main_menu(self._auth, default=action)
            except KeyboardInterrupt:
                return exit_code
            if action is MenuAction.QUIT:
                return exit_code
            if self._show_information(action):
                continue

            try:
                exit_code = self._download(action)
            except GoBack:
                continue  # Esc before the download started: back to the main menu
            except YtGrabError as error:
                self._console.print(f"[red]Error:[/] {escape(str(error))}")
                exit_code = error.exit_code
            if exit_code == EXIT_INTERRUPTED or not self._ask_next():
                return exit_code

    def _ask_next(self) -> bool:
        try:
            return self._prompter.ask_next()
        except GoBack:
            return True

    def _show_information(self, action: MenuAction) -> bool:
        """Handle the entries that don't download anything. False for download entries."""
        if action is MenuAction.SETUP:
            self._prompter.show_page("Setup", setup_table(self._env))
        elif action is MenuAction.HELP:
            # argparse already wrapped the text to the terminal width, and since Python 3.14
            # it colours it with ANSI codes, which from_ansi turns into styles.
            help_text = Text.from_ansi(self._help_text, no_wrap=True, overflow="ignore")
            self._prompter.show_page("Command-line options", help_text)
        elif action is MenuAction.SIGN_IN:
            try:
                self._auth = self._prompter.ask_auth(SIGN_IN_REASON) or AuthConfig()
            except GoBack:
                pass  # keep the current sign-in
            except YtGrabError as error:
                self._console.print(f"[red]{escape(str(error))}")
            self._console.print(f"[dim]Sign-in: {escape(self._auth.describe())}.")
        else:
            return False
        return True

    def _ask_mode_and_urls(self) -> tuple[Mode, list[str]]:
        """Esc on the links returns to the mode question; Esc there leaves (:class:`GoBack`)."""
        while True:
            mode = self._prompter.ask_mode()
            try:
                return mode, self._prompter.ask_urls(mode)
            except GoBack:
                continue

    def _download(self, action: MenuAction) -> int:
        if action is MenuAction.URL_FILE:
            mode, urls = Mode.VIDEO, self._prompter.ask_url_file()
        elif action is MenuAction.QUALITIES:
            mode, urls = self._ask_mode_and_urls()
        else:
            mode = Mode.PLAYLIST if action is MenuAction.PLAYLIST else Mode.VIDEO
            urls = self._prompter.ask_urls(mode)

        options = replace(
            self._base,
            mode=mode,
            urls=tuple(urls),
            auth=self._auth,
            list_qualities=action is MenuAction.QUALITIES,
        )
        app = self._app_factory(options)
        try:
            return app.run()
        finally:
            # Keep a sign-in entered during the run (e.g. for a members-only video).
            self._auth = app.auth
