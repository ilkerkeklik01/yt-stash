"""User interaction. The application only depends on the :class:`Prompter` protocol.

* :class:`TerminalPrompter` shows arrow-key menus and validated text input (questionary).
  Every menu entry carries a one-line explanation, so all features can be found without
  reading the documentation. Esc leaves any question by raising :class:`GoBack`.
* :class:`NonInteractivePrompter` answers every question with its default — used with
  ``--yes`` or when not running in a terminal (scripts, CI, cron).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, TypeVar

import questionary
from prompt_toolkit.input import Input
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent, merge_key_bindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.output import Output
from questionary import Choice, Question, Separator
from rich.console import Console, RenderableType
from rich.markup import escape
from rich.table import Table

from ytgrab.auth import BROWSERS, AuthConfig, BrowserSpec, validate_cookies_file
from ytgrab.browse import list_directory, nearest_existing_dir, quick_places
from ytgrab.downloader import MAX_WORKERS
from ytgrab.errors import UsageError, YtGrabError
from ytgrab.formats import AUDIO_CODECS
from ytgrab.models import (
    AudioOnly,
    DownloadPlan,
    Mode,
    QualityOption,
    Selection,
    SubtitleOptions,
    VideoQuality,
)
from ytgrab.options import CONTAINERS, split_languages
from ytgrab.paths import display_path, expand_path
from ytgrab.urls import normalize_playlist_url, normalize_video_urls, read_url_file, split_urls
from ytgrab.viewer import ESC_TIMEOUT, show_page

T = TypeVar("T")


class GoBack(Exception):
    """The user pressed Esc to leave the current question without answering it.

    Whoever asked decides where "back" leads: the previous question, the review screen or
    the main menu.
    """


class ReviewAction(Enum):
    """What the user picked on the review screen shown before downloading."""

    START = "start"
    QUALITY = "quality"
    DIRECTORY = "directory"
    CONTAINER = "container"
    SUBTITLES = "subtitles"
    OVERWRITE = "overwrite"
    JOBS = "jobs"
    CANCEL = "cancel"


class MenuAction(Enum):
    """Entries of the main menu shown when ytgrab starts without arguments."""

    VIDEOS = "videos"
    PLAYLIST = "playlist"
    URL_FILE = "url-file"
    QUALITIES = "qualities"
    SIGN_IN = "sign-in"
    SETUP = "setup"
    HELP = "help"
    QUIT = "quit"


class Prompter(Protocol):
    def ask_mode(self) -> Mode: ...
    def ask_urls(self, mode: Mode) -> list[str]: ...
    def ask_quality(
        self,
        options: Sequence[QualityOption],
        default_height: int | None,
        video_count: int,
        current: Selection | None = None,
    ) -> Selection: ...
    def ask_directory(self, default: Path) -> Path: ...
    def ask_auth(self, reason: str) -> AuthConfig | None: ...
    def review(self, plan: DownloadPlan, *, video_count: int, target_dir: Path) -> ReviewAction: ...
    def ask_container(self, current: str) -> str: ...
    def ask_subtitles(self, current: SubtitleOptions, *, embed_possible: bool) -> SubtitleOptions: ...
    def ask_overwrite(self, current: bool) -> bool: ...
    def ask_jobs(self, current: int, video_count: int) -> int: ...


class SessionPrompter(Prompter, Protocol):
    """Additional questions of the interactive main menu."""

    def ask_main_menu(self, auth: AuthConfig, default: MenuAction | None = None) -> MenuAction: ...
    def ask_url_file(self) -> list[str]: ...
    def ask_next(self) -> bool: ...
    def show_page(self, title: str, content: RenderableType) -> None: ...


# ---------------------------------------------------------------------- shared wording


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


def plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def describe_selection(selection: Selection) -> str:
    if isinstance(selection, AudioOnly):
        return f"audio only ({selection.codec})"
    if selection.height is None:
        return "best available"
    return f"{selection.height}p (or closest lower)"


def describe_subtitles(subtitles: SubtitleOptions) -> str:
    if not subtitles.enabled:
        return "off"
    where = "embedded in the video" if subtitles.embed else "separate files"
    auto = ", auto-generated too" if subtitles.include_auto_generated else ""
    return f"{', '.join(subtitles.languages)} ({where}{auto})"


AUDIO_HINTS = {
    "m4a": "AAC audio in .m4a. Plays on every phone, computer and car stereo.",
    "mp3": "Converted to .mp3, for older players that don't know m4a.",
    "opus": "YouTube's original audio codec in .opus. Smallest files at the same quality.",
}
CONTAINER_HINTS = {
    "mp4": "Plays on almost every device and editor. Uses mkv for a video whose streams don't fit.",
    "mkv": "Keeps any codec and subtitle format. Some phones and TVs can't play it.",
    "webm": "YouTube's native web format (VP9/AV1 with Opus). Uses mkv when streams don't fit.",
}


def _quality_hint(selection: Selection, counts: dict[int, int], video_count: int) -> str | None:
    if isinstance(selection, AudioOnly):
        return AUDIO_HINTS.get(selection.codec)
    if selection.height is None:
        return "The best stream YouTube offers."
    count = counts.get(selection.height, video_count)
    if video_count > 1 and count < video_count:
        return f"Available in {count} of {video_count} videos. The others get the closest lower quality."
    return None


# ---------------------------------------------------------------------- terminal prompts

STYLE = questionary.Style(
    [
        ("qmark", "fg:ansired bold"),
        ("question", "bold"),
        ("pointer", "fg:ansired bold"),
        ("highlighted", "fg:ansired bold"),
        ("answer", "fg:ansired"),
        ("instruction", "fg:ansibrightblack"),
        ("separator", "fg:ansibrightblack"),
        ("disabled", "fg:ansibrightblack italic"),
    ]
)
QMARK = "▶"
POINTER = "❯"  # noqa: RUF001
SELECT_HINT = "(↑↓ to move, Enter to choose, Esc to go back)"
MENU_HINT = "(↑↓ to move, Enter to choose)"
TEXT_HINT = "(Esc to go back)"
BROWSE_HINT = "(Enter opens, type to filter, Esc goes back)"
_BACK = object()  # result of a question left with Esc


class _StepBack(Exception):
    """Esc in a later step of a multi-step question: return to its first step."""


@contextmanager
def _later_step() -> Iterator[None]:
    try:
        yield
    except GoBack:
        raise _StepBack from None


def _esc_goes_back(question: Question) -> Question:
    """Make Esc end ``question``, erase it from the screen and return :data:`_BACK`."""
    bindings = KeyBindings()

    # eager: Esc must not wait for Alt+key combinations that start with the same byte.
    @bindings.add(Keys.Escape, eager=True)
    def _back(event: KeyPressEvent) -> None:
        event.app.erase_when_done = True
        event.app.exit(result=_BACK)

    app = question.application
    app.key_bindings = merge_key_bindings([app.key_bindings, bindings]) if app.key_bindings else bindings
    app.ttimeoutlen = ESC_TIMEOUT
    return question


def _validator(check: Callable[[str], object]) -> Callable[[str], bool | str]:
    """Adapt a function raising :class:`YtGrabError` to questionary's validate callback."""

    def validate(text: str) -> bool | str:
        try:
            check(text)
        except YtGrabError as error:
            return " ".join(line.strip() for line in str(error).splitlines())
        return True

    return validate


def _check_url_file(text: str) -> None:
    if not read_url_file(text):
        raise UsageError("The file contains no links.")


def _fit_path(text: str, width: int = 60) -> str:
    """Shorten from the left: the end of a path is the part that tells folders apart."""
    return text if len(text) <= width else "…" + text[-(width - 1) :]


def _require(what: str) -> Callable[[str], bool | str]:
    return lambda text: bool(text.strip()) or f"Enter {what}."


def _check_folder_name(name: str) -> bool | str:
    name = name.strip()
    if not name or name in (".", "..") or any(sep in name for sep in "/\\"):
        return "Enter a folder name without slashes."
    return True


class _Browse(Enum):
    """What a browser entry does."""

    OPEN = "open"  # show this folder
    UP = "up"  # show the parent folder, with the cursor on the folder we came from
    PICK = "pick"  # choose this folder or file
    NEW_FOLDER = "new"
    TYPE_PATH = "type"


class TerminalPrompter:
    """Arrow-key menus and validated input in the terminal.

    ``input``/``output`` are only passed in tests, to drive the prompts with key presses.
    """

    def __init__(self, console: Console, *, input: Input | None = None, output: Output | None = None) -> None:
        self._console = console
        self._io: dict[str, Any] = {k: v for k, v in (("input", input), ("output", output)) if v is not None}

    # -------------------------------------------------------------- primitives

    @staticmethod
    def _ask(question: Question, *, can_go_back: bool = True) -> Any:
        if can_go_back:
            _esc_goes_back(question)
        answer = question.unsafe_ask()
        if answer is _BACK:
            raise GoBack
        return answer

    def _select(
        self,
        message: str,
        choices: Sequence[Choice | Separator],
        default: T | None = None,
        *,
        transient: bool = False,
        can_go_back: bool = True,
        searchable: bool = False,
    ) -> T:
        """Arrow-key menu. ``transient`` menus disappear after the choice instead of leaving a line.

        In ``searchable`` menus, typing filters the entries (so j/k cannot move).
        """
        hint = BROWSE_HINT if searchable else SELECT_HINT if can_go_back else MENU_HINT
        question = questionary.select(
            message,
            choices=list(choices),
            default=default,
            qmark=QMARK,
            pointer=POINTER,
            style=STYLE,
            instruction=hint,
            erase_when_done=transient,
            use_search_filter=searchable,
            use_jk_keys=not searchable,
            **self._io,
        )
        return self._ask(question, can_go_back=can_go_back)

    def _text(
        self,
        message: str,
        *,
        default: str = "",
        instruction: str | None = None,
        validate: Callable[[str], bool | str] | None = None,
    ) -> str:
        question = questionary.text(
            message,
            default=default,
            instruction=f"{instruction[:-1]}, Esc to go back)" if instruction else TEXT_HINT,
            validate=validate,
            qmark=QMARK,
            style=STYLE,
            **self._io,
        )
        return self._ask(question)

    def _browse(
        self,
        title: str,
        start: Path,
        *,
        pick_files: bool,
        check: Callable[[str], bool | str] | None = None,
    ) -> Path:
        """Arrow-key file browser: open folders with Enter, ".." goes up, typing filters.

        Picks the shown folder ("Save here"), or with ``pick_files`` a file. ``check``
        validates the pick; a rejected pick is explained and the browser stays open.
        """
        current = nearest_existing_dir(start)
        highlight: tuple[_Browse, Path | None] | None = None
        while True:
            action, target = self._browse_once(title, current, pick_files=pick_files, highlight=highlight)
            highlight = None
            if action is _Browse.UP:
                highlight = (_Browse.OPEN, current)
            if action in (_Browse.OPEN, _Browse.UP):
                assert target is not None
                current = target
                continue
            try:
                if action is _Browse.NEW_FOLDER:
                    current = self._new_folder(current)
                    continue
                if action is _Browse.TYPE_PATH:
                    target = self._typed_path(current)
                    if target.is_dir() and pick_files:
                        current = target
                        continue
            except GoBack:
                continue  # Esc on the name or path: back to the browser
            assert target is not None
            message = check(str(target)) if check else True
            if message is True:
                return target
            self._console.print(f"[red]{escape(str(message))}")

    def _browse_once(
        self,
        title: str,
        current: Path,
        *,
        pick_files: bool,
        highlight: tuple[_Browse, Path | None] | None,
    ) -> tuple[_Browse, Path | None]:
        listing = list_directory(current, include_files=pick_files)
        shown = _fit_path(display_path(current), 50)
        choices: list[Choice | Separator] = []
        if not pick_files:
            choices += [
                Choice("Save here", (_Browse.PICK, current), description=f"Save into {shown}"),
                Choice(
                    "New folder here…",
                    (_Browse.NEW_FOLDER, None),
                    description="Create a folder inside this one and open it.",
                ),
            ]
        choices += [
            Choice(
                "Type a path…",
                (_Browse.TYPE_PATH, None),
                description="Enter a full path, e.g. ~/Videos or D:\\Videos.",
            ),
            Separator(" "),
        ]
        if current.parent != current:
            choices.append(
                Choice(
                    "..", (_Browse.UP, current.parent), description=f"Up to {display_path(current.parent)}"
                )
            )
        choices += [Choice(f"{folder.name}/", (_Browse.OPEN, folder)) for folder in listing.folders]
        choices += [Choice(file.name, (_Browse.PICK, file)) for file in listing.files]
        if listing.error:
            choices.append(Separator(listing.error))
        elif not listing.folders and not listing.files:
            choices.append(Separator("(empty folder)" if pick_files else "(no folders here)"))
        places = [(name, path) for name, path in quick_places() if path != current]
        if places:
            choices.append(Separator(" "))
            choices += [
                Choice(f"Go to {name}", (_Browse.OPEN, path), description=display_path(path))
                for name, path in places
            ]
        return self._select(
            f"{title} {shown}",
            choices,
            highlight,
            transient=True,
            searchable=True,
        )

    def _new_folder(self, parent: Path) -> Path:
        name = self._text("New folder name", validate=_check_folder_name).strip()
        folder = parent / name
        try:
            folder.mkdir(exist_ok=True)
        except OSError as exc:
            self._console.print(
                f"[red]Cannot create '{escape(str(folder))}': {escape(exc.strerror or str(exc))}"
            )
            return parent
        return folder

    def _typed_path(self, current: Path) -> Path:
        typed = self._text(
            "Path",
            default=display_path(current) + os.sep,
            instruction="(~ means your home folder)",
            validate=_require("a path"),
        )
        return expand_path(typed)

    # -------------------------------------------------------------- Prompter

    def ask_mode(self) -> Mode:
        return self._select(
            "What do you want to download?",
            [
                Choice(
                    "One or more videos",
                    Mode.VIDEO,
                    description="Paste one or several video links. Shorts and live replays work too.",
                ),
                Choice(
                    "A whole playlist",
                    Mode.PLAYLIST,
                    description="Every video of a playlist, saved in a folder named after it.",
                ),
            ],
        )

    def ask_urls(self, mode: Mode) -> list[str]:
        if mode is Mode.PLAYLIST:
            answer = self._text("Playlist link", validate=_validator(normalize_playlist_url))
            return [answer.strip()]
        answer = self._text(
            "Video links",
            instruction="(separate several with spaces)",
            validate=_validator(lambda text: normalize_video_urls(split_urls(text))),
        )
        return split_urls(answer)

    def ask_quality(
        self,
        options: Sequence[QualityOption],
        default_height: int | None,
        video_count: int,
        current: Selection | None = None,
    ) -> Selection:
        entries, default_index = quality_choices(options, default_height)
        counts = {o.height: o.video_count for o in options}
        choices: list[Choice | Separator] = []
        for index, (label, selection) in enumerate(entries, start=1):
            if isinstance(selection, AudioOnly) and selection.codec == AUDIO_CODECS[0]:
                choices.append(Separator(" "))
            title = f"{label} (default)" if index == default_index else label
            choices.append(
                Choice(title, selection, description=_quality_hint(selection, counts, video_count))
            )
        values = [selection for _label, selection in entries]
        default = current if current in values else entries[default_index - 1][1]
        return self._select("Quality", choices, default=default)

    def ask_directory(self, default: Path) -> Path:
        return self._browse("Save to", default, pick_files=False)

    def ask_auth(self, reason: str) -> AuthConfig | None:
        self._console.print(f"[yellow]{escape(reason)}")
        while True:  # Esc in a later step comes back to the first question
            try:
                return self._ask_auth_once()
            except _StepBack:
                continue

    def _ask_auth_once(self) -> AuthConfig | None:
        method = self._select(
            "How do you want to sign in?",
            [
                Choice(
                    "Use my browser's YouTube session",
                    "browser",
                    description="Reads the cookies of a browser where you are signed in to YouTube. "
                    "Your system may ask you to allow this.",
                ),
                Choice(
                    "Use a cookies.txt file",
                    "file",
                    description="A Netscape-format file exported with a browser extension.",
                ),
                Choice("Don't sign in", "skip", description="Videos that need an account are skipped."),
            ],
        )
        if method == "skip":
            return None
        with _later_step():
            if method == "file":
                start = Path.home() / "Downloads"
                check = _validator(validate_cookies_file)
                path = self._browse("cookies.txt file", start, pick_files=True, check=check)
                return AuthConfig(cookies_file=validate_cookies_file(path))
            browsers = [Choice(name.capitalize(), name) for name in BROWSERS]
            browser = self._select("Browser", browsers, "firefox")
            profile = self._text("Browser profile", instruction="(leave empty for the default profile)")
            return AuthConfig(browser=BrowserSpec(browser, profile.strip() or None))

    def review(self, plan: DownloadPlan, *, video_count: int, target_dir: Path) -> ReviewAction:
        rows = [
            (
                "Quality",
                describe_selection(plan.selection),
                ReviewAction.QUALITY,
                "Pick another resolution, or download audio only.",
            ),
            (
                "Save to",
                _fit_path(display_path(target_dir)),
                ReviewAction.DIRECTORY,
                "Choose another folder.",
            ),
        ]
        if not isinstance(plan.selection, AudioOnly):
            rows.append(
                (
                    "Video format",
                    plan.container,
                    ReviewAction.CONTAINER,
                    "The file type: mp4, mkv or webm.",
                )
            )
        rows += [
            (
                "Subtitles",
                describe_subtitles(plan.subtitles),
                ReviewAction.SUBTITLES,
                "Download subtitles in your languages, as files or inside the video.",
            ),
            (
                "Existing files",
                "download again" if plan.overwrite else "skip",
                ReviewAction.OVERWRITE,
                "What to do with videos that are already in the folder.",
            ),
        ]
        if video_count > 1:
            rows.append(
                (
                    "Parallel downloads",
                    f"{min(plan.jobs, video_count)} at a time",
                    ReviewAction.JOBS,
                    "How many videos download at the same time.",
                )
            )

        width = max(len(label) for label, *_ in rows) + 3
        choices: list[Choice | Separator] = [
            Choice("Start download", ReviewAction.START, description="Choose a setting below to change it."),
            Separator(" "),
            *(
                Choice(label.ljust(width) + value, action, description=hint)
                for label, value, action, hint in rows
            ),
            Separator(" "),
            Choice("Cancel", ReviewAction.CANCEL, description="Don't download anything."),
        ]
        message = f"Ready to download {plural(video_count, 'video')}"
        return self._select(message, choices, ReviewAction.START, transient=True)

    def ask_container(self, current: str) -> str:
        choices = [Choice(name, name, description=CONTAINER_HINTS[name]) for name in CONTAINERS]
        return self._select("Video format", choices, current)

    def ask_subtitles(self, current: SubtitleOptions, *, embed_possible: bool) -> SubtitleOptions:
        while True:  # Esc in a later step comes back to the first question
            try:
                return self._ask_subtitles_once(current, embed_possible=embed_possible)
            except _StepBack:
                continue

    def _ask_subtitles_once(self, current: SubtitleOptions, *, embed_possible: bool) -> SubtitleOptions:
        current_how = (
            "off" if not current.enabled else "embed" if current.embed and embed_possible else "files"
        )
        how = self._select(
            "Subtitles",
            [
                Choice("No subtitles", "off"),
                Choice(
                    "Save as separate files",
                    "files",
                    description="Subtitle files next to each video. Most players load them automatically.",
                ),
                Choice(
                    "Embed in the video file",
                    "embed",
                    description="One file per video; turn subtitles on in your player.",
                    disabled=None if embed_possible else "needs ffmpeg and a video download",
                ),
            ],
            current_how,
        )
        if how == "off":
            return SubtitleOptions()
        with _later_step():
            languages = self._text(
                "Subtitle languages",
                default=",".join(current.languages) or "en",
                instruction="(language codes such as en,tr, or all)",
                validate=_require("at least one language code"),
            )
            auto = self._select(
                "Use YouTube's auto-generated subtitles?",
                [
                    Choice("Only subtitles written by people", False),
                    Choice(
                        "Also auto-generated ones",
                        True,
                        description="Most videos have them, but they contain speech-recognition errors.",
                    ),
                ],
                current.include_auto_generated,
            )
        return SubtitleOptions(split_languages(languages), auto, how == "embed")

    def ask_overwrite(self, current: bool) -> bool:
        return self._select(
            "Videos that are already in the folder",
            [
                Choice(
                    "Skip them",
                    False,
                    description="Finished files are kept; interrupted downloads continue where they stopped.",
                ),
                Choice(
                    "Download again and replace them",
                    True,
                    description="Use this to get a video you already have in another quality.",
                ),
            ],
            current,
        )

    def ask_jobs(self, current: int, video_count: int) -> int:
        top = min(MAX_WORKERS, video_count)
        choices = [
            Choice(
                f"{n} at a time",
                n,
                description="Many parallel downloads can make YouTube slow you down." if n > 4 else None,
            )
            for n in range(1, top + 1)
        ]
        return self._select("Parallel downloads", choices, min(current, top))

    # -------------------------------------------------------------- SessionPrompter

    def ask_main_menu(self, auth: AuthConfig, default: MenuAction | None = None) -> MenuAction:
        signed_in = "on" if auth.is_configured else "off"
        return self._select(
            "What do you want to do?",
            [
                Choice("Download videos", MenuAction.VIDEOS, description="Paste one or more video links."),
                Choice(
                    "Download a playlist",
                    MenuAction.PLAYLIST,
                    description="Every video of a playlist, in a folder named after it.",
                ),
                Choice(
                    "Download links from a text file",
                    MenuAction.URL_FILE,
                    description="One or more video links per line; lines starting with # are ignored.",
                ),
                Choice(
                    "Show available qualities",
                    MenuAction.QUALITIES,
                    description="See every resolution of videos or a playlist without downloading.",
                ),
                Separator(" "),
                Choice(
                    f"Sign-in ({signed_in})",
                    MenuAction.SIGN_IN,
                    description=f"Members-only, private and age-restricted videos. Now: {auth.describe()}",
                ),
                Choice(
                    "Check setup",
                    MenuAction.SETUP,
                    description="See whether ffmpeg and a JavaScript runtime are installed.",
                ),
                Choice(
                    "Command-line options",
                    MenuAction.HELP,
                    description="Every option, for scripts and one-line commands.",
                ),
                Choice("Quit", MenuAction.QUIT),
            ],
            default,
            can_go_back=False,
        )

    def ask_url_file(self) -> list[str]:
        check = _validator(_check_url_file)
        path = self._browse("Text file with links", Path.cwd(), pick_files=True, check=check)
        return read_url_file(str(path))

    def show_page(self, title: str, content: RenderableType) -> None:
        show_page(title, content, color_system=self._console.color_system, **self._io)

    def ask_next(self) -> bool:
        return self._select(
            "What next?",
            [Choice("Back to the main menu", True), Choice("Quit", False)],
        )


class NonInteractivePrompter:
    """Answers every question with its default; never blocks on input."""

    def ask_mode(self) -> Mode:
        raise UsageError("No mode given. Use 'ytgrab video <url>...' or 'ytgrab playlist <url>'.")

    def ask_urls(self, mode: Mode) -> list[str]:
        raise UsageError("No URL given.")

    def ask_quality(
        self,
        options: Sequence[QualityOption],
        default_height: int | None,
        video_count: int,
        current: Selection | None = None,
    ) -> Selection:
        return current or VideoQuality(default_height)

    def ask_directory(self, default: Path) -> Path:
        return default

    def ask_auth(self, reason: str) -> AuthConfig | None:
        return None

    def review(self, plan: DownloadPlan, *, video_count: int, target_dir: Path) -> ReviewAction:
        return ReviewAction.START

    def ask_container(self, current: str) -> str:
        return current

    def ask_subtitles(self, current: SubtitleOptions, *, embed_possible: bool) -> SubtitleOptions:
        return current

    def ask_overwrite(self, current: bool) -> bool:
        return current

    def ask_jobs(self, current: int, video_count: int) -> int:
        return current
