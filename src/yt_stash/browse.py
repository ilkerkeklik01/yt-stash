"""Directory listings for the interactive file and folder browser (no terminal I/O)."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from yt_stash.i18n import t


@dataclass(frozen=True)
class Listing:
    """Visible subfolders and files of one folder, sorted by name."""

    folders: list[Path] = field(default_factory=list)
    files: list[Path] = field(default_factory=list)
    error: str | None = None  # why the folder could not be read


def _name_key(path: Path) -> tuple[str, str]:
    return (path.name.casefold(), path.name)


def list_directory(directory: Path, *, include_files: bool) -> Listing:
    """Subfolders (and files if wanted) of ``directory``; hidden entries are left out."""
    folders: list[Path] = []
    files: list[Path] = []
    try:
        entries = list(directory.iterdir())
    except OSError as exc:
        return Listing(error=t("browse.cannot_open", reason=exc.strerror or exc))
    for entry in entries:
        if entry.name.startswith("."):
            continue
        try:  # broken links and protected entries are skipped, not fatal
            if entry.is_dir():
                folders.append(entry)
            elif include_files and entry.is_file():
                files.append(entry)
        except OSError:
            continue
    return Listing(sorted(folders, key=_name_key), sorted(files, key=_name_key))


def nearest_existing_dir(path: Path) -> Path:
    """``path`` if it is a folder, otherwise its closest existing parent folder."""
    for candidate in (path, *path.parents):
        if candidate.is_dir():
            return candidate
    return Path.home()


def quick_places(platform: str = sys.platform) -> list[tuple[str, Path]]:
    """Folders worth one keystroke: home, downloads, desktop and the videos folder.

    Each comes with the key of its label (``place.<key>``): folder names on disk are English
    on every system, while the label follows the user's language.
    """
    home = Path.home()
    videos = "Movies" if platform == "darwin" else "Videos"
    places = [("home", home), *((name.lower(), home / name) for name in ("Downloads", "Desktop", videos))]
    return [(key, path) for key, path in places if path.is_dir()]
