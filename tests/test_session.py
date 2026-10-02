"""Tests of the interactive main menu."""

from __future__ import annotations

import io
import json
from dataclasses import dataclass, field

from rich.console import Console

from ytgrab.app import App, RunOptions
from ytgrab.auth import AuthConfig, BrowserSpec
from ytgrab.environment import Environment
from ytgrab.errors import EXIT_INTERRUPTED, UsageError
from ytgrab.i18n import get_language
from ytgrab.models import Mode
from ytgrab.prompts import GoBack, MenuAction
from ytgrab.session import Session, setup_table

from conftest import ScriptedPrompter

FIREFOX = AuthConfig(browser=BrowserSpec("firefox"))
FULL_ENV = Environment(ffmpeg_available=True)


@dataclass
class MenuPrompter(ScriptedPrompter):
    menu: list[MenuAction] = field(default_factory=list)
    next_answers: list[bool] = field(default_factory=list)
    url_file: list[str] = field(default_factory=list)
    menu_defaults: list[MenuAction | None] = field(default_factory=list)
    pages: dict[str, str] = field(default_factory=dict)  # title -> rendered text

    def ask_main_menu(self, auth, default=None):
        self._ask("menu")
        self.menu_defaults.append(default)
        return self.menu.pop(0)

    def ask_url_file(self):
        self._ask("url-file")
        return self.url_file

    def ask_next(self):
        self._ask("next")
        return self.next_answers.pop(0)

    def show_page(self, title, content):
        self._ask("page")
        output = io.StringIO()
        Console(file=output, width=200).print(content)
        self.pages[title] = output.getvalue()


@dataclass
class FakeApp:
    options: RunOptions
    exit_code: int = 0
    auth_after: AuthConfig | None = None
    error: Exception | None = None

    def run(self) -> int:
        if self.error:
            raise self.error
        return self.exit_code

    @property
    def auth(self) -> AuthConfig:
        return self.auth_after or self.options.auth


class Harness:
    def __init__(self, prompter: MenuPrompter, env=FULL_ENV, **app_kwargs):
        self.output = io.StringIO()
        self.prompter = prompter
        self.runs: list[RunOptions] = []
        self.app_kwargs = app_kwargs
        self.session = Session(
            RunOptions(quality=720),
            prompter=prompter,
            console=Console(file=self.output, width=200),
            environment=env,
            app_factory=self.make_app,
            help_text=lambda: (
                "\x1b[1;34musage:\x1b[0m ytgrab [--flags]"
            ),  # coloured like Python 3.14's argparse
        )

    def make_app(self, options: RunOptions) -> App:
        self.runs.append(options)
        return FakeApp(options, **self.app_kwargs)  # type: ignore[return-value]

    @property
    def text(self) -> str:
        return self.output.getvalue()


def test_download_videos_then_quit():
    prompter = MenuPrompter(menu=[MenuAction.VIDEOS], urls=["u1", "u2"], next_answers=[False])
    harness = Harness(prompter)
    assert harness.session.run() == 0
    assert prompter.asked == ["menu", "urls", "next"]
    run = harness.runs[0]
    assert (run.mode, run.urls, run.quality, run.list_qualities) == (Mode.VIDEO, ("u1", "u2"), 720, False)


def test_menu_loops_and_remembers_last_choice():
    prompter = MenuPrompter(
        menu=[MenuAction.PLAYLIST, MenuAction.URL_FILE, MenuAction.QUIT],
        urls=["pl"],
        url_file=["a", "b"],
        next_answers=[True, True],
    )
    harness = Harness(prompter, exit_code=1)
    assert harness.session.run() == 1
    assert [(r.mode, r.urls) for r in harness.runs] == [(Mode.PLAYLIST, ("pl",)), (Mode.VIDEO, ("a", "b"))]
    assert prompter.menu_defaults == [None, MenuAction.PLAYLIST, MenuAction.URL_FILE]


def test_show_qualities_asks_mode_and_lists_only():
    prompter = MenuPrompter(
        menu=[MenuAction.QUALITIES], mode=Mode.PLAYLIST, urls=["pl"], next_answers=[False]
    )
    harness = Harness(prompter)
    harness.session.run()
    assert prompter.asked[:3] == ["menu", "mode", "urls"]
    assert harness.runs[0].list_qualities and harness.runs[0].mode is Mode.PLAYLIST


def test_sign_in_is_used_for_later_downloads_and_can_be_cleared():
    prompter = MenuPrompter(
        menu=[MenuAction.SIGN_IN, MenuAction.VIDEOS, MenuAction.SIGN_IN, MenuAction.VIDEOS, MenuAction.QUIT],
        urls=["u"],
        auth_answers=[FIREFOX, None],
        next_answers=[True, True],
    )
    harness = Harness(prompter)
    harness.session.run()
    assert [r.auth for r in harness.runs] == [FIREFOX, AuthConfig()]
    assert "Sign-in: cookies from browser 'firefox'" in harness.text


def test_sign_in_entered_during_a_download_is_kept():
    prompter = MenuPrompter(
        menu=[MenuAction.VIDEOS, MenuAction.VIDEOS, MenuAction.QUIT], urls=["u"], next_answers=[True, True]
    )
    harness = Harness(prompter, auth_after=FIREFOX)
    harness.session.run()
    assert [r.auth for r in harness.runs] == [AuthConfig(), FIREFOX]


def test_errors_are_shown_and_the_menu_continues():
    prompter = MenuPrompter(menu=[MenuAction.VIDEOS, MenuAction.QUIT], urls=["u"], next_answers=[True])
    harness = Harness(prompter, error=UsageError("Not a valid YouTube video URL"))
    assert harness.session.run() == 2
    assert "Error: Not a valid YouTube video URL" in harness.text


def test_interrupted_download_ends_the_session():
    prompter = MenuPrompter(menu=[MenuAction.VIDEOS], urls=["u"])
    harness = Harness(prompter, exit_code=EXIT_INTERRUPTED)
    assert harness.session.run() == EXIT_INTERRUPTED
    assert "next" not in prompter.asked


def test_information_entries_and_ctrl_c_in_menu():
    class InterruptedMenu(MenuPrompter):
        def ask_main_menu(self, auth, default=None):
            if not self.menu:
                raise KeyboardInterrupt
            return super().ask_main_menu(auth, default)

    prompter = InterruptedMenu(menu=[MenuAction.SETUP, MenuAction.HELP])
    harness = Harness(prompter, env=Environment(ffmpeg_available=False))
    assert harness.session.run() == 0
    assert "ffmpeg was not found" in harness.text  # header warning
    assert prompter.asked == ["menu", "page", "menu", "page"]
    assert "missing" in prompter.pages["Setup"] and "yt-dlp" in prompter.pages["Setup"]
    assert "usage: ytgrab [--flags]" in prompter.pages["Command-line options"]  # escape codes parsed
    assert harness.runs == []


def test_setup_table_install_hints():
    def render(env, platform):
        output = io.StringIO()
        Console(file=output, width=200).print(setup_table(env, platform))
        return output.getvalue()

    missing = Environment(ffmpeg_available=False)
    assert "brew install ffmpeg" in render(missing, "darwin")
    assert "winget install DenoLand.Deno" in render(missing, "win32")
    assert "sudo apt install ffmpeg" in render(missing, "linux")
    found = render(Environment(ffmpeg_available=True, js_runtimes={"deno": {"path": "deno"}}), "linux")
    assert "found" in found and "deno" in found and "Install" not in found


def test_esc_before_download_returns_to_menu():
    prompter = MenuPrompter(
        menu=[MenuAction.VIDEOS, MenuAction.URL_FILE, MenuAction.QUIT],
        escape_at=["urls", "url-file"],
    )
    harness = Harness(prompter)
    assert harness.session.run() == 0
    assert prompter.asked == ["menu", "urls", "menu", "url-file", "menu"]
    assert harness.runs == []


def test_esc_inside_the_run_returns_to_menu():
    prompter = MenuPrompter(menu=[MenuAction.VIDEOS, MenuAction.QUIT], urls=["u"])
    harness = Harness(prompter, error=GoBack())
    assert harness.session.run() == 0
    assert prompter.asked == ["menu", "urls", "menu"]


def test_esc_on_links_of_quality_check_returns_to_mode_question():
    prompter = MenuPrompter(menu=[MenuAction.QUALITIES], urls=["u"], escape_at=["urls"], next_answers=[False])
    harness = Harness(prompter)
    harness.session.run()
    assert prompter.asked == ["menu", "mode", "urls", "mode", "urls", "next"]


def test_esc_on_sign_in_keeps_current_sign_in_and_on_next_goes_to_menu():
    prompter = MenuPrompter(
        menu=[MenuAction.SIGN_IN, MenuAction.SIGN_IN, MenuAction.VIDEOS, MenuAction.QUIT],
        urls=["u"],
        auth_answers=[FIREFOX],
        escape_at=["auth", "next"],
    )
    harness = Harness(prompter)
    harness.session.run()
    # first sign-in is left with Esc, the second sets firefox; Esc on "What next?" shows the menu
    assert harness.runs[0].auth == FIREFOX
    assert prompter.asked[-2:] == ["next", "menu"]


@dataclass
class LanguagePrompter(MenuPrompter):
    languages: list[str] = field(default_factory=list)
    menu_languages: list[str] = field(default_factory=list)  # language each menu was drawn in

    def ask_main_menu(self, auth, default=None):
        self.menu_languages.append(get_language())
        return super().ask_main_menu(auth, default)

    def ask_language(self, current):
        self._ask("language")
        return self.languages.pop(0)


def test_language_applies_at_once_and_is_saved(tmp_path):
    settings = tmp_path / "config.json"
    prompter = LanguagePrompter(
        menu=[MenuAction.LANGUAGE, MenuAction.HELP, MenuAction.QUIT], languages=["tr"]
    )
    harness = Harness(prompter)
    harness.session._settings_file = settings
    harness.session._help_text = lambda: f"help in {get_language()}"
    harness.session.run()
    assert prompter.menu_languages == ["en", "tr", "tr"]
    assert "Dil: Türkçe." in harness.text
    assert prompter.pages["Komut satırı seçenekleri"].strip() == "help in tr"
    assert json.loads(settings.read_text(encoding="utf-8")) == {"language": "tr"}


def test_esc_on_language_keeps_it():
    prompter = LanguagePrompter(menu=[MenuAction.LANGUAGE, MenuAction.QUIT], escape_at=["language"])
    Harness(prompter).session.run()
    assert get_language() == "en"


def test_language_still_switches_when_it_cannot_be_saved(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("", encoding="utf-8")
    prompter = LanguagePrompter(menu=[MenuAction.LANGUAGE, MenuAction.QUIT], languages=["tr"])
    harness = Harness(prompter)
    harness.session._settings_file = blocker / "config.json"
    harness.session.run()
    assert get_language() == "tr"
    assert "kaydedilemedi" in harness.text
