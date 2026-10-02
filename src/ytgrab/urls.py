"""Validation and normalisation of YouTube video and playlist URLs.

Every accepted input is converted to a canonical URL so that the same video given in
different forms (``youtu.be/x``, ``/shorts/x``, ``watch?v=x&t=10``) is downloaded once.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import parse_qs, urlsplit

from ytgrab.errors import UsageError
from ytgrab.paths import expand_path

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_PLAYLIST_ID = re.compile(r"^[A-Za-z0-9_-]{2,64}$")

_YOUTUBE_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtube-nocookie.com",
        "www.youtube-nocookie.com",
    }
)
_SHORT_HOSTS = frozenset({"youtu.be", "www.youtu.be"})
# Paths of the form /<prefix>/<video id>
_PATH_PREFIXES = frozenset({"shorts", "live", "embed", "v", "e"})


def _split(raw: str) -> tuple[str, str, dict[str, list[str]]]:
    """Return (host, path, query) of ``raw``, tolerating a missing scheme."""
    text = raw.strip()
    if not re.match(r"^[a-z][a-z0-9+.-]*://", text, re.IGNORECASE):
        text = "https://" + text
    parts = urlsplit(text)
    host = (parts.hostname or "").lower()
    return host, parts.path, parse_qs(parts.query)


def extract_video_id(raw: str) -> str | None:
    """Return the 11-character video id contained in ``raw``, or ``None``."""
    text = raw.strip()
    if _VIDEO_ID.match(text):
        return text

    host, path, query = _split(text)
    segments = [s for s in path.split("/") if s]
    candidate: str | None = None

    if host in _SHORT_HOSTS:
        candidate = segments[0] if segments else None
    elif host in _YOUTUBE_HOSTS:
        if segments == ["watch"]:
            candidate = query.get("v", [None])[0]
        elif len(segments) >= 2 and segments[0] in _PATH_PREFIXES:
            candidate = segments[1]

    return candidate if candidate and _VIDEO_ID.match(candidate) else None


def extract_playlist_id(raw: str) -> str | None:
    """Return the playlist id (the ``list`` query parameter) contained in ``raw``."""
    host, _path, query = _split(raw)
    if host not in _YOUTUBE_HOSTS and host not in _SHORT_HOSTS:
        return None
    candidate = query.get("list", [None])[0]
    return candidate if candidate and _PLAYLIST_ID.match(candidate) else None


def canonical_video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def canonical_playlist_url(playlist_id: str) -> str:
    return f"https://www.youtube.com/playlist?list={playlist_id}"


def normalize_video_urls(raw_urls: Iterable[str]) -> list[str]:
    """Validate video URLs and return canonical, de-duplicated URLs in input order.

    A ``watch?v=...&list=...`` URL counts as a video: only that video is downloaded.

    Raises:
        UsageError: listing every input that is not a YouTube video URL.
    """
    canonical: list[str] = []
    invalid: list[str] = []
    for raw in raw_urls:
        if not raw.strip():
            continue
        video_id = extract_video_id(raw)
        if video_id is None:
            invalid.append(raw)
            continue
        url = canonical_video_url(video_id)
        if url not in canonical:
            canonical.append(url)

    if invalid:
        hint = ""
        if any(extract_playlist_id(raw) for raw in invalid):
            hint = "\nHint: use 'ytgrab playlist <url>' to download a playlist."
        listing = "\n".join(f"  - {raw}" for raw in invalid)
        raise UsageError(f"Not a valid YouTube video URL:\n{listing}{hint}")
    if not canonical:
        raise UsageError("No video URL was given.")
    return canonical


def normalize_playlist_url(raw: str) -> str:
    """Validate a playlist URL and return its canonical form.

    Raises:
        UsageError: if ``raw`` does not contain a playlist id.
    """
    playlist_id = extract_playlist_id(raw)
    if playlist_id is None:
        hint = ""
        if extract_video_id(raw):
            hint = "\nHint: this is a video URL; use 'ytgrab video <url>' instead."
        raise UsageError(f"Not a valid YouTube playlist URL: {raw}{hint}")
    return canonical_playlist_url(playlist_id)


def split_urls(text: str) -> list[str]:
    """Split user input on whitespace and commas."""
    return [part for part in re.split(r"[\s,]+", text) if part]


def read_url_file(raw_path: str) -> list[str]:
    """URLs listed in a UTF-8 text file (several per line allowed, ``#`` starts a comment line).

    Raises:
        UsageError: if the file cannot be read.
    """
    path = expand_path(raw_path)
    try:
        # utf-8-sig drops the byte-order mark that Windows Notepad writes.
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        reason = exc.strerror if isinstance(exc, OSError) else "not a UTF-8 text file"
        raise UsageError(f"Cannot read URL file '{path}': {reason or exc}") from exc
    return [url for line in lines if not line.lstrip().startswith("#") for url in split_urls(line)]
