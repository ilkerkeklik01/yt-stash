"""Tests of the terminal prompts and progress display.

Prompts are driven with real key presses through prompt_toolkit's pipe input.
"""

import io
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from prompt_toolkit.data_structures import Size
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.output.vt100 import Vt100_Output
from rich.console import Console

from yt_stash.auth import AuthConfig, BrowserSpec
from yt_stash.downloader import DownloadJob, JobResult, JobStatus
from yt_stash.errors import UsageError, VideoError
from yt_stash.i18n import set_language
from yt_stash.models import (
    AudioOnly,
    DownloadPlan,
    Mode,
    ProgressEvent,
    QualityOption,
    Stage,
    SubtitleOptions,
    VideoInfo,
    VideoQuality,
)
from yt_stash.progress import RichProgressReporter, describe_progress, shorten
from yt_stash.prompts import (
    ESC_TIMEOUT,
    GoBack,
    MenuAction,
    NonInteractivePrompter,
    ReviewAction,
    TerminalPrompter,
    describe_subtitles,
    quality_choices,
)
from yt_stash.urls import split_urls

OPTIONS = [
    QualityOption(2160, 60, True, 1),
    QualityOption(1080, 30, False, 2),
    QualityOption(720, 30, False, 2),
]
UP, DOWN, ENTER, CLEAR, ESC = "\x1b[A", "\x1b[B", "\r", "\x15", "\x1b"  # Ctrl+U clears the line
VIDEO_URL = "https://youtu.be/abcdefghijk"


@contextmanager
def keys(*presses: str):
    """A TerminalPrompter that reads ``presses`` as keyboard input.

    Like a person, the typist pauses after Esc: an Esc followed at once by another key
    would be read as one Alt+key combination.
    """

    def type_keys() -> None:
        for press in presses:
            pipe.send_text(press)
            if press == ESC:
                time.sleep(ESC_TIMEOUT * 3)

    with create_pipe_input() as pipe:
        typist = threading.Thread(target=type_keys, daemon=True)
        typist.start()
        output = io.StringIO()
        yield TerminalPrompter(Console(file=output, width=120), input=pipe, output=DummyOutput())
        typist.join()


def plan(**changes) -> DownloadPlan:
    values = dict(
        selection=VideoQuality(1080),
        output_dir=Path("/videos"),
        container="mp4",
        subtitles=SubtitleOptions(),
        overwrite=False,
        jobs=3,
    )
    values.update(changes)
    return DownloadPlan(**values)


def test_quality_choices_default_and_audio_entries():
    entries, default = quality_choices(OPTIONS, 1080)
    assert entries[default - 1][1] == VideoQuality(1080)
    assert [e[1] for e in entries[-3:]] == [AudioOnly("m4a"), AudioOnly("mp3"), AudioOnly("opus")]


def test_quality_choices_without_video_formats():
    entries, default = quality_choices([], None)
    assert entries[0][1] == VideoQuality(None)
    assert default == 1


def test_ask_quality_starts_on_default():
    with keys(ENTER) as prompter:
        assert prompter.ask_quality(OPTIONS, 1080, 2) == VideoQuality(1080)


def test_ask_quality_arrow_keys_move_and_skip_separator():
    with keys(DOWN, ENTER) as prompter:
        assert prompter.ask_quality(OPTIONS, 1080, 2) == VideoQuality(720)
    with keys(DOWN, DOWN, ENTER) as prompter:
        assert prompter.ask_quality(OPTIONS, 1080, 2) == AudioOnly("m4a")


def test_ask_quality_starts_on_current_choice():
    with keys(DOWN, ENTER) as prompter:
        assert prompter.ask_quality(OPTIONS, 1080, 1, current=AudioOnly("mp3")) == AudioOnly("opus")


def test_ask_mode():
    with keys(DOWN, ENTER) as prompter:
        assert prompter.ask_mode() is Mode.PLAYLIST


def test_ask_video_urls_rejects_invalid_input_until_fixed():
    with keys("not-a-link", ENTER, CLEAR, f"{VIDEO_URL}, abcdefghijk", ENTER) as prompter:
        assert prompter.ask_urls(Mode.VIDEO) == [VIDEO_URL, "abcdefghijk"]


def test_ask_playlist_url_rejects_video_links():
    playlist = "https://www.youtube.com/playlist?list=PL123"
    with keys(VIDEO_URL, ENTER, CLEAR, playlist, ENTER) as prompter:
        assert prompter.ask_urls(Mode.PLAYLIST) == [playlist]


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """A folder with two subfolders, a hidden one and text files; the home folder is tmp_path."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows
    root = tmp_path / "root"
    for name in ("alpha", "beta", ".hidden"):
        (root / name).mkdir(parents=True)
    (root / "links.txt").write_text(f"# mine\n{VIDEO_URL}\n", encoding="utf-8")
    (root / "empty.txt").write_text("# nothing\n", encoding="utf-8")
    return root


# Folder browser entries: Save here, New folder, Type a path, (gap), .., alpha/, beta/, (gap), Go to Home
TO_DOTDOT, TO_ALPHA = DOWN * 3, DOWN * 4


def test_browse_save_here_on_enter(tree):
    with keys(ENTER) as prompter:
        assert prompter.ask_directory(tree) == tree


def test_browse_opens_folders_and_goes_up_keeping_the_cursor(tree):
    with keys(TO_ALPHA, ENTER, ENTER) as prompter:
        assert prompter.ask_directory(tree) == tree / "alpha"
    # from alpha: ".." goes up with the cursor on alpha/, so Enter opens alpha again
    with keys(TO_DOTDOT, ENTER, ENTER, ENTER) as prompter:
        assert prompter.ask_directory(tree / "alpha") == tree / "alpha"


def test_browse_typing_filters_folders(tree):
    with keys("bet", ENTER, ENTER) as prompter:
        assert prompter.ask_directory(tree) == tree / "beta"


def test_browse_quick_places(tree):
    with keys(UP, ENTER, ENTER) as prompter:  # the last entry is "Go to Home"
        assert prompter.ask_directory(tree) == tree.parent


def test_browse_new_folder(tree):
    with keys(DOWN, ENTER, "clips", ENTER, ENTER) as prompter:
        assert prompter.ask_directory(tree) == tree / "clips"
    assert (tree / "clips").is_dir()


def test_browse_rejects_bad_folder_names_and_esc_returns_to_browser(tree):
    with keys(DOWN, ENTER, "a/b", ENTER, ESC, ENTER) as prompter:
        assert prompter.ask_directory(tree) == tree
    assert not (tree / "a").exists()


def test_browse_type_a_path(tree):
    with keys(DOWN * 2, ENTER, CLEAR, "~/later", ENTER) as prompter:
        assert prompter.ask_directory(tree) == tree.parent / "later"


def test_browse_starts_at_nearest_existing_folder(tree):
    with keys(ENTER) as prompter:
        assert prompter.ask_directory(tree / "missing" / "deeper") == tree


def test_browse_esc_goes_back(tree):
    with keys(ESC) as prompter, pytest.raises(GoBack):
        prompter.ask_directory(tree)


def test_ask_auth_browser_with_profile():
    with keys(ENTER, UP, UP, UP, ENTER, "Work", ENTER) as prompter:  # firefox -> chrome
        assert prompter.ask_auth("why") == AuthConfig(browser=BrowserSpec("chrome", "Work"))


def test_ask_auth_skip():
    with keys(DOWN, DOWN, DOWN, ENTER) as prompter:
        assert prompter.ask_auth("why") is None


def test_ask_auth_file_is_picked_in_browser_and_validated(tree):
    empty = tree / "empty-cookies.txt"
    empty.touch()
    cookies = tree / "cookies.txt"
    cookies.write_text("x", encoding="utf-8")
    # starts in ~/Downloads, which does not exist: the home folder is shown instead
    with keys(DOWN, ENTER, "root", ENTER, "empty-c", ENTER, "cookies.t", ENTER) as prompter:
        assert prompter.ask_auth("why") == AuthConfig(cookies_file=cookies)


def test_review_starts_on_enter():
    with keys(ENTER) as prompter:
        assert prompter.review(plan(), video_count=2, target_dir=Path("/videos")) is ReviewAction.START


@pytest.mark.parametrize(
    ("downs", "selection", "action"),
    [
        (1, VideoQuality(1080), ReviewAction.QUALITY),
        (3, VideoQuality(1080), ReviewAction.CONTAINER),
        (3, AudioOnly("mp3"), ReviewAction.SUBTITLES),  # no video format row for audio
        (6, VideoQuality(1080), ReviewAction.JOBS),
        (7, VideoQuality(1080), ReviewAction.CANCEL),
    ],
)
def test_review_rows(downs, selection, action):
    with keys(DOWN * downs, ENTER) as prompter:
        assert prompter.review(plan(selection=selection), video_count=2, target_dir=Path("/v")) is action


def test_review_hides_parallel_downloads_for_one_video():
    with keys(DOWN * 6, ENTER) as prompter:
        assert prompter.review(plan(), video_count=1, target_dir=Path("/v")) is ReviewAction.CANCEL


def test_ask_container_starts_on_current():
    with keys(DOWN, ENTER) as prompter:
        assert prompter.ask_container("mkv") == "webm"


def test_ask_subtitles_files_with_languages_and_auto():
    with keys(DOWN, ENTER, CLEAR, "en, tr", ENTER, DOWN, ENTER) as prompter:
        result = prompter.ask_subtitles(SubtitleOptions(), embed_possible=True)
    assert result == SubtitleOptions(("en", "tr"), include_auto_generated=True, embed=False)


def test_ask_subtitles_embed_and_off():
    with keys(DOWN, DOWN, ENTER, ENTER, ENTER) as prompter:
        assert prompter.ask_subtitles(SubtitleOptions(), embed_possible=True) == SubtitleOptions(
            ("en",), embed=True
        )
    with keys(UP, ENTER) as prompter:
        assert prompter.ask_subtitles(SubtitleOptions(("en",)), embed_possible=True) == SubtitleOptions()


def test_ask_subtitles_embedding_disabled_without_ffmpeg():
    # From "separate files" the disabled "embed" entry is skipped and the menu wraps to "off".
    with keys(DOWN, ENTER) as prompter:
        assert prompter.ask_subtitles(SubtitleOptions(("en",)), embed_possible=False) == SubtitleOptions()


def test_ask_overwrite_and_jobs():
    with keys(DOWN, ENTER) as prompter:
        assert prompter.ask_overwrite(False) is True
    with keys(ENTER) as prompter:
        assert prompter.ask_jobs(5, video_count=3) == 3
    with keys(UP, ENTER) as prompter:
        assert prompter.ask_jobs(2, video_count=8) == 1


def test_main_menu_url_file_and_next(tmp_path):
    url_file = tmp_path / "links.txt"
    url_file.write_text(f"# mine\n{VIDEO_URL}\n", encoding="utf-8")
    empty = tmp_path / "empty.txt"
    empty.write_text("# nothing\n", encoding="utf-8")
    with keys(ENTER) as prompter:
        assert prompter.ask_main_menu(AuthConfig()) is MenuAction.VIDEOS
    with keys(UP, ENTER) as prompter:
        assert prompter.ask_main_menu(AuthConfig(), default=MenuAction.PLAYLIST) is MenuAction.VIDEOS
    # "Type a path…" is the first entry of a file browser; the empty file is rejected
    with keys(ENTER, CLEAR, str(empty), ENTER, ENTER, CLEAR, str(url_file), ENTER) as prompter:
        assert prompter.ask_url_file() == [VIDEO_URL]
    with keys(DOWN, ENTER) as prompter:
        assert prompter.ask_next() is False


@pytest.mark.parametrize(
    "ask",
    [
        lambda p: p.ask_mode(),
        lambda p: p.ask_urls(Mode.VIDEO),
        lambda p: p.ask_quality(OPTIONS, 1080, 1),
        lambda p: p.ask_directory(Path("/default")),
        lambda p: p.review(plan(), video_count=1, target_dir=Path("/v")),
        lambda p: p.ask_container("mp4"),
        lambda p: p.ask_jobs(2, 4),
        lambda p: p.ask_url_file(),
        lambda p: p.ask_next(),
        lambda p: p.ask_auth("why"),
    ],
)
def test_esc_leaves_any_question(ask):
    with keys("abc", ESC) as prompter, pytest.raises(GoBack):
        ask(prompter)


def test_esc_in_later_step_returns_to_first_step():
    # Subtitles: files -> Esc on languages -> back to "how", which starts on "off" again
    with keys(DOWN, ENTER, ESC, ENTER) as prompter:
        assert prompter.ask_subtitles(SubtitleOptions(), embed_possible=True) == SubtitleOptions()
    # Sign-in: browser -> Esc on browser list -> back to method -> skip (fourth entry)
    with keys(ENTER, ESC, DOWN, DOWN, DOWN, ENTER) as prompter:
        assert prompter.ask_auth("why") is None


def test_esc_does_nothing_on_main_menu():
    with keys(ESC, DOWN, ENTER) as prompter:
        assert prompter.ask_main_menu(AuthConfig()) is MenuAction.PLAYLIST


def test_url_file_browser_rejects_files_without_links(tree, monkeypatch):
    monkeypatch.chdir(tree)
    with keys("empty", ENTER, "links", ENTER) as prompter:
        assert prompter.ask_url_file() == [VIDEO_URL]


def test_show_page_closes_with_esc_or_q():
    for close in (ESC, "q", ENTER):
        with keys(DOWN, " ", close) as prompter:
            prompter.show_page("Setup", "\n".join(f"line {i}" for i in range(100)))


def test_describe_subtitles():
    assert describe_subtitles(SubtitleOptions()) == "off"
    assert describe_subtitles(SubtitleOptions(("en", "tr"), True, True)) == (
        "en, tr (embedded in the video, auto-generated too)"
    )


def test_non_interactive_prompter():
    p = NonInteractivePrompter()
    assert p.ask_quality(OPTIONS, 1080, 1) == VideoQuality(1080)
    assert p.ask_directory(Path("/d")) == Path("/d")
    assert p.ask_auth("?") is None
    assert p.review(plan(), video_count=1, target_dir=Path("/d")) is ReviewAction.START
    assert p.ask_container("mkv") == "mkv"
    assert p.ask_jobs(4, 9) == 4 and p.ask_overwrite(True) is True
    assert p.ask_subtitles(SubtitleOptions(("en",)), embed_possible=False) == SubtitleOptions(("en",))
    with pytest.raises(UsageError):
        p.ask_mode()
    with pytest.raises(UsageError):
        p.ask_urls(Mode.VIDEO)


def test_split_urls():
    assert split_urls(" a,,b\tc\n") == ["a", "b", "c"]


def test_shorten():
    assert shorten("abc", 5) == "abc"
    assert shorten("abcdefgh", 5) == "abcd…"


def test_describe_progress():
    event = ProgressEvent(
        "id", Stage.VIDEO, downloaded_bytes=1_000_000, total_bytes=4_000_000, speed=500_000, eta=75
    )
    assert describe_progress(event) == "video: 1.0 MB/4.0 MB • 500.0 kB/s • ETA 01:15"
    assert describe_progress(ProgressEvent("id", Stage.PROCESSING)) == "merging / converting…"
    assert "ETA 1:01:01" in describe_progress(ProgressEvent("id", Stage.AUDIO, eta=3661))


def test_rich_reporter_prints_results():
    output = io.StringIO()
    console = Console(file=output, width=120)
    video = VideoInfo(id="abc", title="[weird] title", url="u")
    job = DownloadJob(video, {})
    with RichProgressReporter(console, total_jobs=3) as reporter:
        reporter.job_started(video)
        reporter.job_progress(video, ProgressEvent("abc", Stage.VIDEO, 10, 100))
        reporter.job_progress(video, ProgressEvent("abc", Stage.AUDIO, 5, 50))
        reporter.job_retrying(video, 1, 3, VideoError("HTTP Error 429"))
        reporter.job_finished(JobResult(job, JobStatus.COMPLETED, path=Path("/x/file.mp4")))
        reporter.job_finished(JobResult(job, JobStatus.SKIPPED))
        reporter.job_finished(JobResult(job, JobStatus.FAILED, error=VideoError("Video unavailable")))
    text = output.getvalue()
    assert "[weird] title" in text
    assert "file.mp4" in text and "already downloaded" in text and "Video unavailable" in text
    assert "retrying in 3s" in text


def test_language_menu():
    with keys(DOWN * 5, ENTER) as prompter:
        assert prompter.ask_main_menu(AuthConfig()) is MenuAction.LANGUAGE
    with keys(DOWN, ENTER) as prompter:
        assert prompter.ask_language("en") == "tr"
    with keys(ENTER) as prompter:
        assert prompter.ask_language("tr") == "tr"


def test_turkish_progress_text():
    set_language("tr")
    event = ProgressEvent("id", Stage.AUDIO, downloaded_bytes=1_000_000, eta=75)
    assert describe_progress(event) == "ses: 1.0 MB • kalan 01:15"
    output = io.StringIO()
    video = VideoInfo(id="abc", title="title", url="u")
    with RichProgressReporter(Console(file=output, width=120), total_jobs=1) as reporter:
        reporter.job_retrying(video, 1, 3, VideoError("HTTP Error 429"))
        reporter.job_finished(JobResult(DownloadJob(video, {}), JobStatus.SKIPPED))
    assert "3 sn sonra yeniden denenecek (deneme 2)" in output.getvalue()
    assert "(zaten indirilmiş)" in output.getvalue()


PASTE_START, PASTE_END = "\x1b[200~", "\x1b[201~"  # how terminals wrap pasted text
SECRET = "AKfycb-secret-value"


def test_paste_cookies_is_a_sign_in_method():
    with keys(DOWN, DOWN, ENTER, f"SID={SECRET}; HSID=x", ENTER) as prompter:
        auth = prompter.ask_auth("why")
    assert auth.pasted.count == 2 and f"SID\t{SECRET}" in auth.pasted.netscape


def test_multi_line_paste_is_one_answer_and_bad_pastes_are_rejected():
    cookies_txt = f"# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\t{SECRET}\n"
    with keys(
        ENTER,
        PASTE_START + "nonsense" + PASTE_END,
        ENTER,
        CLEAR,
        PASTE_START + cookies_txt + PASTE_END,
        ENTER,
    ) as prompter:
        assert prompter.ask_pasted_cookies().count == 1


def test_pasted_cookies_are_never_shown():
    screen = io.StringIO()
    output = Vt100_Output(screen, lambda: Size(rows=24, columns=200), term="xterm")
    with create_pipe_input() as pipe:
        pipe.send_text(PASTE_START + f"SID={SECRET};\nHSID=x" + PASTE_END + ENTER)
        prompter = TerminalPrompter(Console(file=io.StringIO()), input=pipe, output=output)
        assert prompter.ask_pasted_cookies().count == 2
    assert SECRET not in screen.getvalue()
    assert re.search(r"\[\d+ characters\]", screen.getvalue())
