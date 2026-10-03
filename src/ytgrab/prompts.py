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
from prompt_toolkit.layout.processors import Processor, Transformation, TransformationInput
from prompt_toolkit.output import Output
from questionary import Choice, Question, Separator
from rich.console import Console, RenderableType
from rich.markup import escape
from rich.table import Table

from ytgrab.auth import (
    BROWSERS,
    AuthConfig,
    BrowserSpec,
    PastedCookies,
    parse_pasted_cookies,
    validate_cookies_file,
)
from ytgrab.browse import list_directory, nearest_existing_dir, quick_places
from ytgrab.downloader import MAX_WORKERS
from ytgrab.errors import UsageError, YtGrabError
from ytgrab.formats import AUDIO_CODECS
from ytgrab.i18n import LANGUAGES, get_language, t, tn
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
    LANGUAGE = "language"
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
    def ask_language(self, current: str) -> str: ...
    def show_page(self, title: str, content: RenderableType) -> None: ...


# ---------------------------------------------------------------------- shared wording


def quality_choices(
    options: Sequence[QualityOption], default_height: int | None
) -> tuple[list[tuple[str, Selection]], int]:
    """Menu entries ``(label, selection)`` and the 1-based index of the default entry."""
    entries: list[tuple[str, Selection]] = [(o.label, VideoQuality(o.height)) for o in options]
    if not entries:
        entries.append((t("quality.best"), VideoQuality(None)))
    entries += [(t("quality.audio", codec=codec), AudioOnly(codec)) for codec in AUDIO_CODECS]

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
    table = Table(title=t("quality.table_title"), title_justify="left", show_edge=False)
    table.add_column("#", justify="right", style="bold")
    table.add_column(t("quality.column_quality"))
    if video_count > 1:
        table.add_column(t("quality.column_available"), justify="right")

    counts = {o.height: o.video_count for o in options}
    for index, (label, selection) in enumerate(entries, start=1):
        text = f"{label} [green]{t('quality.default')}[/]" if index == default_index else label
        row = [str(index), text]
        if video_count > 1:
            if isinstance(selection, VideoQuality) and selection.height in counts:
                row.append(t("quality.available_in", count=counts[selection.height], total=video_count))
            else:
                row.append(t("quality.all"))
        table.add_row(*row)
    return table


def describe_selection(selection: Selection) -> str:
    if isinstance(selection, AudioOnly):
        return t("selection.audio", codec=selection.codec)
    if selection.height is None:
        return t("selection.best")
    return t("selection.height", height=selection.height)


def describe_subtitles(subtitles: SubtitleOptions) -> str:
    if not subtitles.enabled:
        return t("subs.off")
    auto = subtitles.include_auto_generated
    if subtitles.embed:
        key = "subs.embedded_auto" if auto else "subs.embedded"
    else:
        key = "subs.files_auto" if auto else "subs.files"
    return t(key, languages=", ".join(subtitles.languages))


def _quality_hint(selection: Selection, counts: dict[int, int], video_count: int) -> str | None:
    if isinstance(selection, AudioOnly):
        return t(f"hint.audio.{selection.codec}")
    if selection.height is None:
        return t("quality.hint_best")
    count = counts.get(selection.height, video_count)
    if video_count > 1 and count < video_count:
        return t("quality.hint_partial", count=count, total=video_count)
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


# Stands for a pasted line break, so a multi-line paste stays in the one-line input.
_LINE_BREAK = "\x1e"


class _Concealed(Processor):
    """Shows how many characters were entered instead of the secret itself."""

    def apply_transformation(self, transformation_input: TransformationInput) -> Transformation:
        size = len(transformation_input.document.text)
        shown = t("sign_in.paste_size", count=size) if size else ""
        return Transformation(
            [("class:answer", shown)],
            source_to_display=lambda _position: len(shown),
            display_to_source=lambda _position: size,
        )


def _keep_pasted_lines(question: Question) -> Question:
    """Insert a multi-line paste into ``question`` as one line instead of answering at its first line."""
    bindings = KeyBindings()

    @bindings.add(Keys.BracketedPaste)
    def _paste(event: KeyPressEvent) -> None:
        text = event.data.replace("\r\n", "\n").replace("\r", "\n")
        event.current_buffer.insert_text(text.replace("\n", _LINE_BREAK))

    app = question.application
    app.key_bindings = merge_key_bindings([app.key_bindings, bindings]) if app.key_bindings else bindings
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
        raise UsageError(t("prompt.no_links"))


def _fit_path(text: str, width: int = 60) -> str:
    """Shorten from the left: the end of a path is the part that tells folders apart."""
    return text if len(text) <= width else "…" + text[-(width - 1) :]


def _require(message_key: str) -> Callable[[str], bool | str]:
    return lambda text: bool(text.strip()) or t(message_key)


def _check_folder_name(name: str) -> bool | str:
    name = name.strip()
    if not name or name in (".", "..") or any(sep in name for sep in "/\\"):
        return t("prompt.bad_folder_name")
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
        hint = t("hint.browse" if searchable else "hint.select" if can_go_back else "hint.menu")
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
        secret: bool = False,
    ) -> str:
        """Text input. A ``secret`` is never shown: only its length, and pasted lines stay one answer."""
        question = questionary.text(
            message,
            default=default,
            instruction=t("hint.text_with", hint=instruction) if instruction else t("hint.text"),
            validate=validate,
            qmark=QMARK,
            style=STYLE,
            **({"input_processors": [_Concealed()]} if secret else {}),
            **self._io,
        )
        return self._ask(_keep_pasted_lines(question) if secret else question)

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
                Choice(
                    t("browse.save_here"),
                    (_Browse.PICK, current),
                    description=t("browse.save_into", path=shown),
                ),
                Choice(
                    t("browse.new_folder"),
                    (_Browse.NEW_FOLDER, None),
                    description=t("browse.new_folder_desc"),
                ),
            ]
        choices += [
            Choice(t("browse.type_path"), (_Browse.TYPE_PATH, None), description=t("browse.type_path_desc")),
            Separator(" "),
        ]
        if current.parent != current:
            choices.append(
                Choice(
                    "..",
                    (_Browse.UP, current.parent),
                    description=t("browse.up", path=display_path(current.parent)),
                )
            )
        choices += [Choice(f"{folder.name}/", (_Browse.OPEN, folder)) for folder in listing.folders]
        choices += [Choice(file.name, (_Browse.PICK, file)) for file in listing.files]
        if listing.error:
            choices.append(Separator(listing.error))
        elif not listing.folders and not listing.files:
            choices.append(Separator(t("browse.empty_folder" if pick_files else "browse.no_folders")))
        places = [(key, path) for key, path in quick_places() if path != current]
        if places:
            choices.append(Separator(" "))
            choices += [
                Choice(
                    t("browse.go_to", place=t(f"place.{key}")),
                    (_Browse.OPEN, path),
                    description=display_path(path),
                )
                for key, path in places
            ]
        return self._select(
            f"{title} {shown}",
            choices,
            highlight,
            transient=True,
            searchable=True,
        )

    def _new_folder(self, parent: Path) -> Path:
        name = self._text(t("browse.folder_name"), validate=_check_folder_name).strip()
        folder = parent / name
        try:
            folder.mkdir(exist_ok=True)
        except OSError as exc:
            reason = exc.strerror or str(exc)
            self._console.print(f"[red]{escape(t('browse.cannot_create', path=folder, reason=reason))}")
            return parent
        return folder

    def _typed_path(self, current: Path) -> Path:
        typed = self._text(
            t("browse.path"),
            default=display_path(current) + os.sep,
            instruction=t("browse.path_hint"),
            validate=_require("prompt.require_path"),
        )
        return expand_path(typed)

    # -------------------------------------------------------------- Prompter

    def ask_mode(self) -> Mode:
        return self._select(
            t("mode.prompt"),
            [
                Choice(t("mode.videos"), Mode.VIDEO, description=t("mode.videos_desc")),
                Choice(t("mode.playlist"), Mode.PLAYLIST, description=t("mode.playlist_desc")),
            ],
        )

    def ask_urls(self, mode: Mode) -> list[str]:
        if mode is Mode.PLAYLIST:
            answer = self._text(t("urls.playlist_prompt"), validate=_validator(normalize_playlist_url))
            return [answer.strip()]
        answer = self._text(
            t("urls.video_prompt"),
            instruction=t("urls.video_hint"),
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
            title = f"{label} {t('quality.default')}" if index == default_index else label
            choices.append(
                Choice(title, selection, description=_quality_hint(selection, counts, video_count))
            )
        values = [selection for _label, selection in entries]
        default = current if current in values else entries[default_index - 1][1]
        return self._select(t("quality.prompt"), choices, default=default)

    def ask_directory(self, default: Path) -> Path:
        return self._browse(t("directory.prompt"), default, pick_files=False)

    def ask_auth(self, reason: str) -> AuthConfig | None:
        self._console.print(f"[yellow]{escape(reason)}")
        while True:  # Esc in a later step comes back to the first question
            try:
                return self._ask_auth_once()
            except _StepBack:
                continue

    def _ask_auth_once(self) -> AuthConfig | None:
        method = self._select(
            t("sign_in.prompt"),
            [
                Choice(t("sign_in.browser"), "browser", description=t("sign_in.browser_desc")),
                Choice(t("sign_in.file"), "file", description=t("sign_in.file_desc")),
                Choice(t("sign_in.paste"), "paste", description=t("sign_in.paste_desc")),
                Choice(t("sign_in.skip"), "skip", description=t("sign_in.skip_desc")),
            ],
        )
        if method == "skip":
            return None
        with _later_step():
            if method == "paste":
                return AuthConfig(pasted=self.ask_pasted_cookies())
            if method == "file":
                start = Path.home() / "Downloads"
                check = _validator(validate_cookies_file)
                path = self._browse(t("sign_in.file_prompt"), start, pick_files=True, check=check)
                return AuthConfig(cookies_file=validate_cookies_file(path))
            browsers = [Choice(name.capitalize(), name) for name in BROWSERS]
            browser = self._select(t("sign_in.browser_prompt"), browsers, "firefox")
            profile = self._text(t("sign_in.profile_prompt"), instruction=t("sign_in.profile_hint"))
            return AuthConfig(browser=BrowserSpec(browser, profile.strip() or None))

    def ask_pasted_cookies(self) -> PastedCookies:
        """Cookies pasted into the terminal; they are not shown on screen."""

        def parse(text: str) -> PastedCookies:
            return parse_pasted_cookies(text.replace(_LINE_BREAK, "\n"))

        answer = self._text(
            t("sign_in.paste_prompt"),
            instruction=t("sign_in.paste_hint"),
            validate=_validator(parse),
            secret=True,
        )
        return parse(answer)

    def review(self, plan: DownloadPlan, *, video_count: int, target_dir: Path) -> ReviewAction:
        rows = [
            (
                t("quality.prompt"),
                describe_selection(plan.selection),
                ReviewAction.QUALITY,
                t("review.quality_desc"),
            ),
            (
                t("directory.prompt"),
                _fit_path(display_path(target_dir)),
                ReviewAction.DIRECTORY,
                t("review.directory_desc"),
            ),
        ]
        if not isinstance(plan.selection, AudioOnly):
            rows.append(
                (t("review.container"), plan.container, ReviewAction.CONTAINER, t("review.container_desc"))
            )
        rows += [
            (
                t("review.subtitles"),
                describe_subtitles(plan.subtitles),
                ReviewAction.SUBTITLES,
                t("review.subtitles_desc"),
            ),
            (
                t("review.existing"),
                t("review.existing_replace" if plan.overwrite else "review.existing_skip"),
                ReviewAction.OVERWRITE,
                t("review.existing_desc"),
            ),
        ]
        if video_count > 1:
            rows.append(
                (
                    t("review.jobs"),
                    t("jobs.at_a_time", count=min(plan.jobs, video_count)),
                    ReviewAction.JOBS,
                    t("review.jobs_desc"),
                )
            )

        width = max(len(label) for label, *_ in rows) + 3
        choices: list[Choice | Separator] = [
            Choice(t("review.start"), ReviewAction.START, description=t("review.start_desc")),
            Separator(" "),
            *(
                Choice(label.ljust(width) + value, action, description=hint)
                for label, value, action, hint in rows
            ),
            Separator(" "),
            Choice(t("review.cancel"), ReviewAction.CANCEL, description=t("review.cancel_desc")),
        ]
        return self._select(tn("review.prompt", video_count), choices, ReviewAction.START, transient=True)

    def ask_container(self, current: str) -> str:
        choices = [Choice(name, name, description=t(f"hint.container.{name}")) for name in CONTAINERS]
        return self._select(t("review.container"), choices, current)

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
            t("review.subtitles"),
            [
                Choice(t("subs.none"), "off"),
                Choice(t("subs.as_files"), "files", description=t("subs.as_files_desc")),
                Choice(
                    t("subs.embed"),
                    "embed",
                    description=t("subs.embed_desc"),
                    disabled=None if embed_possible else t("subs.embed_disabled"),
                ),
            ],
            current_how,
        )
        if how == "off":
            return SubtitleOptions()
        with _later_step():
            languages = self._text(
                t("subs.languages_prompt"),
                default=",".join(current.languages) or "en",
                instruction=t("subs.languages_hint"),
                validate=_require("prompt.require_language"),
            )
            auto = self._select(
                t("subs.auto_prompt"),
                [
                    Choice(t("subs.only_human"), False),
                    Choice(t("subs.also_auto"), True, description=t("subs.also_auto_desc")),
                ],
                current.include_auto_generated,
            )
        return SubtitleOptions(split_languages(languages), auto, how == "embed")

    def ask_overwrite(self, current: bool) -> bool:
        return self._select(
            t("overwrite.prompt"),
            [
                Choice(t("overwrite.skip"), False, description=t("overwrite.skip_desc")),
                Choice(t("overwrite.replace"), True, description=t("overwrite.replace_desc")),
            ],
            current,
        )

    def ask_jobs(self, current: int, video_count: int) -> int:
        top = min(MAX_WORKERS, video_count)
        choices = [
            Choice(t("jobs.at_a_time", count=n), n, description=t("jobs.many_desc") if n > 4 else None)
            for n in range(1, top + 1)
        ]
        return self._select(t("review.jobs"), choices, min(current, top))

    # -------------------------------------------------------------- SessionPrompter

    def ask_main_menu(self, auth: AuthConfig, default: MenuAction | None = None) -> MenuAction:
        # Built anew on every call, so a language change shows on the next menu.
        sign_in = t("menu.sign_in_on" if auth.is_configured else "menu.sign_in_off")
        return self._select(
            t("menu.prompt"),
            [
                Choice(t("menu.videos"), MenuAction.VIDEOS, description=t("menu.videos_desc")),
                Choice(t("menu.playlist"), MenuAction.PLAYLIST, description=t("menu.playlist_desc")),
                Choice(t("menu.url_file"), MenuAction.URL_FILE, description=t("menu.url_file_desc")),
                Choice(t("menu.qualities"), MenuAction.QUALITIES, description=t("menu.qualities_desc")),
                Separator(" "),
                Choice(sign_in, MenuAction.SIGN_IN, description=t("menu.sign_in_desc", auth=auth.describe())),
                Choice(
                    t("menu.language", name=LANGUAGES[get_language()]),
                    MenuAction.LANGUAGE,
                    description=t("menu.language_desc"),
                ),
                Choice(t("menu.setup"), MenuAction.SETUP, description=t("menu.setup_desc")),
                Choice(t("menu.help"), MenuAction.HELP, description=t("menu.help_desc")),
                Choice(t("menu.quit"), MenuAction.QUIT),
            ],
            default,
            can_go_back=False,
        )

    def ask_url_file(self) -> list[str]:
        check = _validator(_check_url_file)
        path = self._browse(t("url_file.prompt"), Path.cwd(), pick_files=True, check=check)
        return read_url_file(str(path))

    def show_page(self, title: str, content: RenderableType) -> None:
        show_page(title, content, color_system=self._console.color_system, **self._io)

    def ask_next(self) -> bool:
        return self._select(
            t("next.prompt"),
            [Choice(t("next.menu"), True), Choice(t("menu.quit"), False)],
        )

    def ask_language(self, current: str) -> str:
        choices = [Choice(name, code) for code, name in LANGUAGES.items()]
        return self._select(t("language.prompt"), choices, current)


class NonInteractivePrompter:
    """Answers every question with its default; never blocks on input."""

    def ask_mode(self) -> Mode:
        raise UsageError(t("prompt.no_mode"))

    def ask_urls(self, mode: Mode) -> list[str]:
        raise UsageError(t("prompt.no_url"))

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
