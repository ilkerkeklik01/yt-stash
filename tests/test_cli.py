from pathlib import Path

import pytest

from ytgrab import __version__
from ytgrab.cli import build_parser, main, options_from_args
from ytgrab.errors import AuthConfigError, UsageError
from ytgrab.models import Mode
from ytgrab.prompts import GoBack


def parse(*argv: str):
    return options_from_args(build_parser().parse_args(list(argv)))


def test_no_arguments_starts_wizard():
    assert parse().mode is None


def test_video_options():
    options = parse(
        "video",
        "URL1",
        "URL2",
        "-q",
        "720p",
        "-o",
        "~/out",
        "-j",
        "5",
        "--container",
        "mkv",
        "--subs",
        "en, tr",
        "--auto-subs",
        "--embed-subs",
        "--overwrite",
        "--list-qualities",
    )
    assert options.mode is Mode.VIDEO
    assert options.urls == ("URL1", "URL2")
    assert options.quality == 720
    assert options.output_dir == (Path.home() / "out").resolve()
    assert options.jobs == 5
    assert options.container == "mkv"
    assert options.subtitles.languages == ("en", "tr")
    assert options.subtitles.include_auto_generated and options.subtitles.embed
    assert options.overwrite
    assert options.list_qualities


def test_playlist_options():
    options = parse(
        "playlist", "https://www.youtube.com/playlist?list=PL1", "--cookies-from-browser", "firefox"
    )
    assert options.mode is Mode.PLAYLIST
    assert options.urls == ("https://www.youtube.com/playlist?list=PL1",)
    assert options.auth.browser.name == "firefox"


def test_audio_only_defaults_to_m4a():
    assert parse("video", "x", "-a").audio_codec == "m4a"
    assert parse("video", "x", "--audio-only", "mp3").audio_codec == "mp3"


def test_from_file(tmp_path):
    url_file = tmp_path / "urls.txt"
    url_file.write_text("# comment\nA B,C\n\n  D\n", encoding="utf-8")
    assert parse("video", "X", "--from-file", str(url_file)).urls == ("X", "A", "B", "C", "D")
    with pytest.raises(UsageError):
        parse("video", "--from-file", str(tmp_path / "missing.txt"))


@pytest.mark.parametrize(
    ("argv", "error"),
    [
        (("video", "x", "-a", "-q", "720"), UsageError),
        (("video", "x", "--embed-subs"), UsageError),
        (("video", "x", "-q", "hd"), UsageError),
        (("video", "x", "--cookies-from-browser", "lynx"), AuthConfigError),
        (("video", "x", "--cookies", "/definitely/missing.txt"), AuthConfigError),
    ],
)
def test_invalid_combinations(argv, error):
    with pytest.raises(error):
        parse(*argv)


@pytest.mark.parametrize("jobs", ["0", "17", "many"])
def test_invalid_jobs_exit_with_usage_error(jobs, capsys):
    with pytest.raises(SystemExit) as excinfo:
        build_parser().parse_args(["video", "x", "-j", jobs])
    assert excinfo.value.code == 2


def test_version(capsys):
    with pytest.raises(SystemExit):
        main(["--version"])
    assert __version__ in capsys.readouterr().out


def test_main_reports_usage_errors_with_exit_code_2(capsys):
    assert main(["video", "not-a-url", "--yes"]) == 2
    assert "Not a valid YouTube video URL" in capsys.readouterr().out


def test_main_non_interactive_without_mode(capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert main([]) == 2


def test_options_before_subcommand_are_kept():
    options = parse("-q", "720", "-o", "/tmp/x", "-j", "2", "video", "URL")
    assert options.quality == 720 and options.jobs == 2 and options.mode is Mode.VIDEO
    assert options.output_dir == Path("/tmp/x").resolve()
    # values after the subcommand win, defaults never overwrite earlier values
    assert parse("-j", "2", "video", "URL", "-j", "5").jobs == 5
    assert parse("--overwrite", "video", "URL").overwrite


def test_options_without_subcommand_for_wizard():
    options = parse("-y", "-q", "best", "--cookies-from-browser", "firefox")
    assert options.mode is None and options.quality == "best"
    assert options.auth.browser.name == "firefox"


def test_from_file_ignores_windows_byte_order_mark(tmp_path):
    url_file = tmp_path / "urls.txt"
    url_file.write_bytes("\ufeff# saved by Notepad\r\nhttps://youtu.be/dQw4w9WgXcQ\r\n".encode())
    assert parse("video", "--from-file", str(url_file)).urls == ("https://youtu.be/dQw4w9WgXcQ",)


def test_from_file_rejects_binary(tmp_path):
    url_file = tmp_path / "urls.bin"
    url_file.write_bytes(b"\xff\xfe\x00\x01binary")
    with pytest.raises(UsageError, match="UTF-8"):
        parse("video", "--from-file", str(url_file))


def test_esc_with_nothing_to_go_back_to_cancels(capsys, monkeypatch):
    def leave(self):
        raise GoBack

    monkeypatch.setattr("ytgrab.app.App.run", leave)
    assert main(["video", "https://youtu.be/dQw4w9WgXcQ", "--yes"]) == 0
    assert "Cancelled" in capsys.readouterr().out
