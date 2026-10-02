"""Detection of external programs: ffmpeg and a JavaScript runtime."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

Which = Callable[[str], str | None]

# yt-dlp runtime key -> executable name. YouTube requires a JS runtime to solve
# its player challenges; without one only a few low-quality formats are available.
JS_RUNTIME_EXECUTABLES = {"deno": "deno", "node": "node", "bun": "bun", "quickjs": "qjs"}


@dataclass(frozen=True)
class Environment:
    ffmpeg_available: bool
    ffmpeg_location: Path | None = None
    js_runtimes: dict[str, dict[str, str]] = field(default_factory=dict)


def detect_ffmpeg(location: Path | None = None, which: Which = shutil.which) -> bool:
    """Whether ffmpeg is usable, either at ``location`` (file or folder) or on PATH."""
    if location is not None:
        if location.is_file():
            return True
        return any((location / name).is_file() for name in ("ffmpeg", "ffmpeg.exe"))
    return which("ffmpeg") is not None


def detect_js_runtimes(which: Which = shutil.which) -> dict[str, dict[str, str]]:
    """Return yt-dlp's ``js_runtimes`` param for every runtime found on PATH."""
    runtimes: dict[str, dict[str, str]] = {}
    for key, executable in JS_RUNTIME_EXECUTABLES.items():
        path = which(executable)
        if path:
            runtimes[key] = {"path": path}
    return runtimes


def detect_environment(ffmpeg_location: Path | None = None, which: Which = shutil.which) -> Environment:
    return Environment(
        ffmpeg_available=detect_ffmpeg(ffmpeg_location, which),
        ffmpeg_location=ffmpeg_location,
        js_runtimes=detect_js_runtimes(which),
    )
