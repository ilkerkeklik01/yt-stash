"""Tests of the settings file."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yt_stash.settings import config_path, load_settings, save_setting

HOME = Path("/home/me")


def test_config_path_per_platform():
    assert config_path("linux", {}, HOME) == HOME / ".config" / "yt-stash" / "config.json"
    assert config_path("linux", {"XDG_CONFIG_HOME": "/xdg"}, HOME) == Path("/xdg/yt-stash/config.json")
    assert (
        config_path("darwin", {}, HOME)
        == HOME / "Library" / "Application Support" / "yt-stash" / "config.json"
    )
    assert config_path("win32", {"APPDATA": "/appdata"}, HOME) == Path("/appdata/yt-stash/config.json")
    assert config_path("win32", {}, HOME) == HOME / "AppData" / "Roaming" / "yt-stash" / "config.json"


def test_missing_or_damaged_file_means_no_settings(tmp_path):
    path = tmp_path / "config.json"
    assert load_settings(path) == {}
    path.write_text("{not json", encoding="utf-8")
    assert load_settings(path) == {}
    path.write_text("[1, 2]", encoding="utf-8")
    assert load_settings(path) == {}


def test_save_keeps_other_settings(tmp_path):
    path = tmp_path / "nested" / "config.json"
    save_setting(path, "future", True)
    save_setting(path, "language", "tr")
    assert json.loads(path.read_text(encoding="utf-8")) == {"future": True, "language": "tr"}
    assert load_settings(path) == {"future": True, "language": "tr"}
    assert not path.with_name("config.json.tmp").exists()


def test_save_reports_unwritable_folder(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("", encoding="utf-8")
    with pytest.raises(OSError):
        save_setting(blocker / "config.json", "language", "tr")


def test_failed_save_leaves_no_temporary_file(tmp_path):
    path = tmp_path / "config.json"
    path.mkdir()  # a folder in the way: the file cannot replace it
    with pytest.raises(OSError):
        save_setting(path, "language", "tr")
    assert list(tmp_path.iterdir()) == [path]
