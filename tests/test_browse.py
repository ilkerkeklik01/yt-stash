"""Tests of directory listings for the file browser and of the page viewer's scrolling."""

from pathlib import Path

from ytgrab.browse import list_directory, nearest_existing_dir, quick_places
from ytgrab.viewer import Page, render_lines


def test_list_directory_sorts_and_hides_dot_entries(tmp_path):
    for name in ("b", "A", ".git"):
        (tmp_path / name).mkdir()
    for name in ("z.txt", "a.txt", ".env"):
        (tmp_path / name).touch()
    listing = list_directory(tmp_path, include_files=True)
    assert [p.name for p in listing.folders] == ["A", "b"]
    assert [p.name for p in listing.files] == ["a.txt", "z.txt"]
    assert list_directory(tmp_path, include_files=False).files == []


def test_list_directory_reports_unreadable_folder(tmp_path):
    listing = list_directory(tmp_path / "missing", include_files=False)
    assert listing.error and listing.error.startswith("Cannot open this folder")


def test_nearest_existing_dir(tmp_path):
    assert nearest_existing_dir(tmp_path / "x" / "y") == tmp_path
    (tmp_path / "file").touch()
    assert nearest_existing_dir(tmp_path / "file") == tmp_path


def test_quick_places(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / "Downloads").mkdir()
    (tmp_path / "Movies").mkdir()
    assert [name for name, _ in quick_places("darwin")] == ["home", "downloads", "movies"]
    assert [name for name, _ in quick_places("linux")] == ["home", "downloads"]


def test_page_scrolls_within_bounds_and_rerenders_on_resize():
    page = Page("\n".join(f"line {i}" for i in range(50)), color_system=None)
    page.layout(80)
    assert len(page.lines) == 50
    assert page.visible(10) == range(0, 10)
    page.scroll(45, 10)
    assert page.visible(10) == range(40, 50)  # stops at the end
    page.scroll(-100, 10)
    assert page.top == 0
    page.top = 45
    assert page.visible(60) == range(0, 50)  # taller window after a resize


def test_render_lines_wraps_to_width():
    assert len(render_lines("word " * 40, width=20, color_system=None)) > 5
    assert "\x1b[" in "".join(render_lines("[red]x", width=20, color_system="standard"))
