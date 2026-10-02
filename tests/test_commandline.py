"""Tests of the equivalent command shown after interactive runs."""

import os
from pathlib import Path

import pytest

from ytgrab.auth import AuthConfig, BrowserSpec
from ytgrab.commandline import equivalent_command
from ytgrab.models import AudioOnly, DownloadPlan, Mode, SubtitleOptions, VideoQuality

URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
posix_paths = pytest.mark.skipif(os.name == "nt", reason="expects POSIX path separators")


def plan(**changes) -> DownloadPlan:
    values = dict(
        selection=VideoQuality(1080),
        output_dir=Path("/data/My Videos"),
        container="mp4",
        subtitles=SubtitleOptions(),
        overwrite=False,
        jobs=3,
    )
    values.update(changes)
    return DownloadPlan(**values)


@pytest.fixture(autouse=True)
def posix(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")


@posix_paths
def test_defaults_are_omitted_and_values_quoted():
    command = equivalent_command(Mode.VIDEO, [URL], plan(), AuthConfig())
    assert command == f"ytgrab video '{URL}' -q 1080 -o '/data/My Videos' --yes"


@posix_paths
def test_every_setting_is_rendered():
    command = equivalent_command(
        Mode.VIDEO,
        [URL],
        plan(
            selection=VideoQuality(None),
            container="mkv",
            subtitles=SubtitleOptions(("en", "tr"), include_auto_generated=True, embed=True),
            overwrite=True,
            jobs=5,
        ),
        AuthConfig(browser=BrowserSpec("chrome", "Profile 1")),
    )
    assert command.endswith(
        "-q best --container mkv -o '/data/My Videos' --subs en,tr --auto-subs --embed-subs "
        "--overwrite -j 5 --cookies-from-browser 'chrome:Profile 1' --yes"
    )


def test_audio_only_has_no_quality_or_container():
    command = equivalent_command(
        Mode.VIDEO, [URL], plan(selection=AudioOnly("mp3"), container="mkv"), AuthConfig()
    )
    assert "-a mp3" in command and "-q" not in command and "--container" not in command


@posix_paths
def test_home_paths_keep_tilde_unquoted():
    command = equivalent_command(
        Mode.PLAYLIST,
        ["https://www.youtube.com/playlist?list=PL1"],
        plan(output_dir=Path.home() / "a b"),
        AuthConfig(),
    )
    assert "-o ~/'a b'" in command


def test_many_urls_become_a_placeholder():
    command = equivalent_command(Mode.VIDEO, [URL] * 4, plan(), AuthConfig())
    assert command.startswith("ytgrab video URL... -q")


def test_windows_quoting(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    command = equivalent_command(Mode.VIDEO, [URL], plan(), AuthConfig())
    assert f"ytgrab video {URL} -q 1080" in command and '"' in command
