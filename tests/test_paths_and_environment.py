import os
import sys
from pathlib import Path

import pytest

from ytgrab.environment import detect_environment, detect_ffmpeg, detect_js_runtimes
from ytgrab.errors import OutputDirectoryError
from ytgrab.paths import ensure_writable_directory, expand_path, sanitize_component


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("My Playlist", "My Playlist"),
        ('a/b\\c:d*e?f"g<h>i|j', "a_b_c_d_e_f_g_h_i_j"),
        ("trailing dots...", "trailing dots"),
        ("  lots   of\tspace  ", "lots of space"),
        ("CON", "_CON"),
        ("com1.txt", "_com1.txt"),
        ("$HOME and %APPDATA%", "_HOME and _APPDATA_"),
        ("a\x9bb\x7f", "a_b_"),
        ("", "untitled"),
        ("...", "untitled"),
        ("Türkçe 🎵 名前", "Türkçe 🎵 名前"),
    ],
)
def test_sanitize_component(name, expected):
    assert sanitize_component(name) == expected


def test_sanitize_component_limits_length():
    assert len(sanitize_component("x" * 500)) == 100


def test_expand_path(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("YTGRAB_TEST_DIR", str(tmp_path))
    assert expand_path(f"'$YTGRAB_TEST_DIR{os.sep}sub'") == (tmp_path / "sub").resolve()
    assert expand_path("~") == Path.home().resolve()


def test_ensure_writable_directory_creates_nested(tmp_path: Path):
    target = tmp_path / "a" / "b"
    assert ensure_writable_directory(target) == target
    assert target.is_dir()


def test_ensure_writable_directory_rejects_files(tmp_path: Path):
    file = tmp_path / "file"
    file.touch()
    with pytest.raises(OutputDirectoryError, match="not a directory"):
        ensure_writable_directory(file)
    with pytest.raises(OutputDirectoryError, match="Cannot create"):
        ensure_writable_directory(file / "child")


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="POSIX permissions, non-root")
def test_ensure_writable_directory_rejects_read_only(tmp_path: Path):
    read_only = tmp_path / "ro"
    read_only.mkdir()
    read_only.chmod(0o500)
    try:
        with pytest.raises(OutputDirectoryError, match="not writable"):
            ensure_writable_directory(read_only)
    finally:
        read_only.chmod(0o700)


def fake_which(available: dict[str, str]):
    return lambda name: available.get(name)


def test_detect_js_runtimes():
    which = fake_which({"node": "/usr/bin/node", "qjs": "/usr/bin/qjs"})
    assert detect_js_runtimes(which) == {
        "node": {"path": "/usr/bin/node"},
        "quickjs": {"path": "/usr/bin/qjs"},
    }
    assert detect_js_runtimes(fake_which({})) == {}


def test_detect_ffmpeg(tmp_path: Path):
    assert detect_ffmpeg(None, fake_which({"ffmpeg": "/bin/ffmpeg"}))
    assert not detect_ffmpeg(None, fake_which({}))
    assert not detect_ffmpeg(tmp_path, fake_which({"ffmpeg": "/bin/ffmpeg"}))  # explicit location wins
    (tmp_path / "ffmpeg.exe").touch()
    assert detect_ffmpeg(tmp_path)
    assert detect_ffmpeg(tmp_path / "ffmpeg.exe")


def test_detect_environment():
    env = detect_environment(None, fake_which({"ffmpeg": "f", "deno": "d"}))
    assert env.ffmpeg_available
    assert env.js_runtimes == {"deno": {"path": "d"}}
