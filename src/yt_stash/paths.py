"""File-system helpers: target directory validation and portable folder names."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from yt_stash.errors import OutputDirectoryError
from yt_stash.i18n import t

# "$" and "%" are dropped too: yt-dlp expands environment variables in the output folder.
_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*$%\x00-\x1f\x7f-\x9f]')
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
)


def sanitize_component(name: str, max_length: int = 100, fallback: str = "untitled") -> str:
    """Make ``name`` safe to use as a single folder name on Windows, macOS and Linux."""
    cleaned = re.sub(r"\s+", " ", name).strip()  # tabs/newlines become plain spaces first
    cleaned = _ILLEGAL_CHARS.sub("_", cleaned)
    cleaned = cleaned[:max_length].rstrip(" .")  # Windows forbids trailing dots/spaces
    if not cleaned or cleaned in (".", ".."):
        return fallback
    if cleaned.split(".")[0].upper() in _WINDOWS_RESERVED:
        cleaned = f"_{cleaned}"
    return cleaned


def expand_path(raw: str | os.PathLike[str]) -> Path:
    """Expand ``~`` and environment variables, strip surrounding quotes, make absolute."""
    text = os.fspath(raw).strip().strip("'\"")
    return Path(os.path.expandvars(os.path.expanduser(text))).resolve()


def display_path(path: Path) -> str:
    """``~/Downloads`` instead of ``/Users/me/Downloads``: shorter and the same on every machine."""
    try:
        return str(Path("~") / path.relative_to(Path.home()))
    except ValueError:
        return str(path)


def default_download_dir() -> Path:
    """``~/Downloads`` when it exists, otherwise the current directory."""
    downloads = Path.home() / "Downloads"
    return downloads if downloads.is_dir() else Path.cwd()


def ensure_writable_directory(path: Path) -> Path:
    """Create ``path`` (with parents) if needed and verify files can be written there.

    Raises:
        OutputDirectoryError: with a message explaining what is wrong.
    """
    if path.exists() and not path.is_dir():
        raise OutputDirectoryError(t("paths.not_a_directory", path=path))
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OutputDirectoryError(t("paths.cannot_create", path=path, reason=exc.strerror or exc)) from exc

    # os.access() is unreliable on Windows and network shares, so actually try a write.
    try:
        with tempfile.TemporaryFile(dir=path):
            pass
    except OSError as exc:
        raise OutputDirectoryError(t("paths.not_writable", path=path, reason=exc.strerror or exc)) from exc
    return path
