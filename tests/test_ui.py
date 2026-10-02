"""Tests of the terminal prompts and progress display."""

import io
from pathlib import Path

import pytest
from rich.console import Console

from ytgrab.auth import AuthConfig, BrowserSpec
from ytgrab.downloader import DownloadJob, JobResult, JobStatus
from ytgrab.errors import AuthConfigError, UsageError, VideoError
from ytgrab.models import AudioOnly, Mode, ProgressEvent, QualityOption, Stage, VideoInfo, VideoQuality
from ytgrab.progress import RichProgressReporter, describe_progress, shorten
from ytgrab.prompts import NonInteractivePrompter, RichPrompter, quality_choices, split_urls

OPTIONS = [
    QualityOption(2160, 60, True, 1),
    QualityOption(1080, 30, False, 2),
    QualityOption(720, 30, False, 2),
]


def prompter(answers: str):
    output = io.StringIO()
    console = Console(file=output, width=120)
    return RichPrompter(console, stream=io.StringIO(answers)), output


def test_quality_choices_default_and_audio_entries():
    entries, default = quality_choices(OPTIONS, 1080)
    assert entries[default - 1][1] == VideoQuality(1080)
    assert [e[1] for e in entries[-3:]] == [AudioOnly("m4a"), AudioOnly("mp3"), AudioOnly("opus")]


def test_quality_choices_without_video_formats():
    entries, default = quality_choices([], None)
    assert entries[0][1] == VideoQuality(None)
    assert default == 1


def test_ask_quality_accepts_default_on_enter():
    rich_prompter, output = prompter("\n")
    assert rich_prompter.ask_quality(OPTIONS, 1080, 2) == VideoQuality(1080)
    text = output.getvalue()
    assert "2160p60 HDR" in text and "1/2 videos" in text and "(default)" in text


def test_ask_quality_rejects_invalid_then_accepts():
    rich_prompter, _ = prompter("99\nabc\n1\n")
    assert rich_prompter.ask_quality(OPTIONS, 1080, 1) == VideoQuality(2160)


def test_ask_quality_audio():
    rich_prompter, _ = prompter("5\n")
    assert rich_prompter.ask_quality(OPTIONS, 1080, 1) == AudioOnly("mp3")


def test_ask_mode_urls_directory_confirm(tmp_path):
    rich_prompter, _ = prompter(f"playlist\nhttps://x\n{tmp_path}\nn\n")
    assert rich_prompter.ask_mode() is Mode.PLAYLIST
    assert rich_prompter.ask_urls(Mode.PLAYLIST) == ["https://x"]
    assert rich_prompter.ask_directory(Path("/default")) == tmp_path.resolve()
    assert rich_prompter.confirm("ok?") is False


def test_ask_video_urls_splits_input():
    rich_prompter, _ = prompter("a b, c\n")
    assert rich_prompter.ask_urls(Mode.VIDEO) == ["a", "b", "c"]


def test_ask_auth_browser_with_profile():
    rich_prompter, _ = prompter("browser\nchrome\nWork\n")
    assert rich_prompter.ask_auth("why") == AuthConfig(browser=BrowserSpec("chrome", "Work"))


def test_ask_auth_skip_and_file(tmp_path):
    assert prompter("skip\n")[0].ask_auth("why") is None
    cookies = tmp_path / "c.txt"
    cookies.write_text("x", encoding="utf-8")
    assert prompter(f"file\n{cookies}\n")[0].ask_auth("why") == AuthConfig(cookies_file=cookies.resolve())
    with pytest.raises(AuthConfigError):
        prompter(f"file\n{tmp_path / 'missing'}\n")[0].ask_auth("why")


def test_non_interactive_prompter():
    p = NonInteractivePrompter()
    assert p.ask_quality(OPTIONS, 1080, 1) == VideoQuality(1080)
    assert p.ask_directory(Path("/d")) == Path("/d")
    assert p.confirm("?") is True
    assert p.ask_auth("?") is None
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
