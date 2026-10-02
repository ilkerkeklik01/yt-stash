"""User interaction. The application only depends on the :class:`Prompter` protocol.

* :class:`RichPrompter` asks questions in the terminal.
* :class:`NonInteractivePrompter` answers every question with its default — used with
  ``--yes`` or when stdin is not a terminal (scripts, CI, cron).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path
from typing import IO, Protocol

from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

from ytgrab.auth import BROWSERS, AuthConfig, BrowserSpec, validate_cookies_file
from ytgrab.errors import UsageError
from ytgrab.formats import AUDIO_CODECS
from ytgrab.models import AudioOnly, Mode, QualityOption, Selection, VideoQuality
from ytgrab.paths import expand_path


class Prompter(Protocol):
    def ask_mode(self) -> Mode: ...
    def ask_urls(self, mode: Mode) -> list[str]: ...
    def ask_quality(
        self, options: Sequence[QualityOption], default_height: int | None, video_count: int
    ) -> Selection: ...
    def ask_directory(self, default: Path) -> Path: ...
    def confirm(self, message: str, default: bool = True) -> bool: ...
    def ask_auth(self, reason: str) -> AuthConfig | None: ...


def quality_choices(
    options: Sequence[QualityOption], default_height: int | None
) -> tuple[list[tuple[str, Selection]], int]:
    """Menu entries ``(label, selection)`` and the 1-based index of the default entry."""
    entries: list[tuple[str, Selection]] = [(o.label, VideoQuality(o.height)) for o in options]
    if not entries:
        entries.append(("Best available", VideoQuality(None)))
    entries += [(f"Audio only ({codec})", AudioOnly(codec)) for codec in AUDIO_CODECS]

    default_index = 1
    for index, (_label, selection) in enumerate(entries, start=1):
        if isinstance(selection, VideoQuality) and selection.height == default_height:
            default_index = index
            break
    return entries, default_index


def render_quality_table(
    options: Sequence[QualityOption], default_height: int | None, video_count: int
) -> Table:
    """Table of all choices; shows per-resolution availability for multi-video batches."""
    entries, default_index = quality_choices(options, default_height)
    table = Table(title="Available qualities", title_justify="left", show_edge=False)
    table.add_column("#", justify="right", style="bold")
    table.add_column("Quality")
    if video_count > 1:
        table.add_column("Available in", justify="right")

    counts = {o.height: o.video_count for o in options}
    for index, (label, selection) in enumerate(entries, start=1):
        text = f"{label} [green](default)[/]" if index == default_index else label
        row = [str(index), text]
        if video_count > 1:
            if isinstance(selection, VideoQuality) and selection.height in counts:
                row.append(f"{counts[selection.height]}/{video_count} videos")
            else:
                row.append("all")
        table.add_row(*row)
    return table


def split_urls(text: str) -> list[str]:
    """Split user input on whitespace and commas."""
    return [part for part in re.split(r"[\s,]+", text) if part]


class RichPrompter:
    """Interactive prompts in the terminal."""

    def __init__(self, console: Console, stream: IO[str] | None = None) -> None:
        self._console = console
        self._stream = stream

    def _ask(self, question: str, **kwargs: object) -> str:
        return Prompt.ask(question, console=self._console, stream=self._stream, **kwargs)  # type: ignore[arg-type]

    def ask_mode(self) -> Mode:
        answer = self._ask(
            "Download a single [b]video[/] (or several) or a whole [b]playlist[/]?",
            choices=[m.value for m in Mode],
            default=Mode.VIDEO.value,
        )
        return Mode(answer)

    def ask_urls(self, mode: Mode) -> list[str]:
        if mode is Mode.PLAYLIST:
            return [self._ask("Playlist URL").strip()]
        return split_urls(self._ask("Video URL(s) [dim](separate several with spaces)[/]"))

    def ask_quality(
        self, options: Sequence[QualityOption], default_height: int | None, video_count: int
    ) -> Selection:
        entries, default_index = quality_choices(options, default_height)
        self._console.print(render_quality_table(options, default_height, video_count))
        if video_count > 1:
            self._console.print("[dim]Videos without the chosen quality get the closest lower one.[/]")
        answer = self._ask(
            "Select quality",
            choices=[str(i) for i in range(1, len(entries) + 1)],
            default=str(default_index),
            show_choices=False,
        )
        return entries[int(answer) - 1][1]

    def ask_directory(self, default: Path) -> Path:
        return expand_path(self._ask("Target directory", default=str(default)))

    def confirm(self, message: str, default: bool = True) -> bool:
        return Confirm.ask(message, console=self._console, default=default, stream=self._stream)

    def ask_auth(self, reason: str) -> AuthConfig | None:
        self._console.print(f"[yellow]{reason}")
        method = self._ask(
            "Sign in using cookies from your [b]browser[/], a cookies.txt [b]file[/], or [b]skip[/]?",
            choices=["browser", "file", "skip"],
            default="browser",
        )
        if method == "skip":
            return None
        if method == "file":
            return AuthConfig(cookies_file=validate_cookies_file(self._ask("Path to cookies.txt")))
        browser = self._ask("Browser", choices=list(BROWSERS), default="firefox")
        profile = self._ask("Browser profile [dim](empty for the default profile)[/]", default="")
        return AuthConfig(browser=BrowserSpec(browser, profile.strip() or None))


class NonInteractivePrompter:
    """Answers every question with its default; never blocks on input."""

    def ask_mode(self) -> Mode:
        raise UsageError("No mode given. Use 'ytgrab video <url>...' or 'ytgrab playlist <url>'.")

    def ask_urls(self, mode: Mode) -> list[str]:
        raise UsageError("No URL given.")

    def ask_quality(
        self, options: Sequence[QualityOption], default_height: int | None, video_count: int
    ) -> Selection:
        return VideoQuality(default_height)

    def ask_directory(self, default: Path) -> Path:
        return default

    def confirm(self, message: str, default: bool = True) -> bool:
        return True

    def ask_auth(self, reason: str) -> AuthConfig | None:
        return None
