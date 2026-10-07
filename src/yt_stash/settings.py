"""Settings kept between runs (currently the language chosen in the main menu).

They are stored as JSON in the usual per-user configuration folder of each OS. A missing or
damaged file simply means "no saved settings"; keys this version doesn't know are kept.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def config_path(
    platform: str = sys.platform, environ: Mapping[str, str] = os.environ, home: Path | None = None
) -> Path:
    """``%APPDATA%\\yt-stash``, ``~/Library/Application Support/yt-stash`` or ``~/.config/yt-stash``."""

    def base_dir(variable: str, *fallback: str) -> Path:
        value = environ.get(variable)
        return Path(value) if value else (home or Path.home()).joinpath(*fallback)

    if platform == "win32":
        base = base_dir("APPDATA", "AppData", "Roaming")
    elif platform == "darwin":
        base = (home or Path.home()) / "Library" / "Application Support"
    else:
        base = base_dir("XDG_CONFIG_HOME", ".config")
    return base / "yt-stash" / "config.json"


def load_settings(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_setting(path: Path, key: str, value: Any) -> None:
    """Store one setting, keeping the others.

    The file is replaced in one step, so an interrupted write never leaves half a file.

    Raises:
        OSError: if the folder or file cannot be written.
    """
    settings = load_settings(path)
    settings[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise
