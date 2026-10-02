"""Exception hierarchy and classification of yt-dlp error messages.

yt-dlp reports almost every failure as a ``DownloadError`` with a human readable
message. To react sensibly (retry, ask for authentication, skip) we classify those
messages into a small set of :class:`ErrorKind` values.
"""

from __future__ import annotations

import re
from enum import Enum

from ytgrab.i18n import t


class ErrorKind(Enum):
    """Why a single video could not be probed or downloaded."""

    AUTH_REQUIRED = "sign-in required (members-only, private or age-restricted)"
    NOT_YET_AVAILABLE = "not available yet (upcoming premiere or live stream)"
    LIVE_IN_PROGRESS = "live stream in progress"
    GEO_BLOCKED = "blocked in your country"
    UNAVAILABLE = "video unavailable"
    RATE_LIMITED = "rate limited by YouTube"
    NETWORK = "network error"
    DISK = "disk or permission error"
    UNKNOWN = "unexpected error"

    @property
    def is_transient(self) -> bool:
        """Whether retrying the same operation later may succeed."""
        return self in (ErrorKind.RATE_LIMITED, ErrorKind.NETWORK)

    @property
    def label(self) -> str:
        """The kind in the user's language (the value stays English, like yt-dlp's messages)."""
        return t(f"kind.{self.name.lower()}")


# Order matters: the first matching pattern wins.
_PATTERNS: tuple[tuple[ErrorKind, re.Pattern[str]], ...] = tuple(
    (kind, re.compile(pattern, re.IGNORECASE))
    for kind, pattern in (
        (
            ErrorKind.DISK,
            r"no space left|errno 28|disk quota|permission denied|read-only file system|"
            r"file name too long|errno 36|access is denied|winerror (5|32)\b|used by another process",
        ),
        # A broken TLS setup never heals by retrying: keep it out of NETWORK.
        (ErrorKind.UNKNOWN, r"certificate.verify.failed"),
        (ErrorKind.RATE_LIMITED, r"http error 429|too many requests|rate.?limit"),
        (
            ErrorKind.AUTH_REQUIRED,
            r"members[- ]only|join this channel|channel'?s members|sign in to confirm|"
            r"private video|login required|registered users|--cookies|requires payment|"
            r"inappropriate for some users|age[- ]restricted",
        ),
        (ErrorKind.NOT_YET_AVAILABLE, r"premieres in|live event will begin|is_upcoming"),
        (ErrorKind.GEO_BLOCKED, r"available in your country|geo.?restrict|blocked it in your country"),
        (
            ErrorKind.UNAVAILABLE,
            r"video (is )?unavailable|has been removed|no longer available|account .* terminated|"
            r"does not exist|copyright|this video is not available|unsupported url",
        ),
        (
            ErrorKind.NETWORK,
            r"timed? ?out|connection (reset|refused|aborted)|temporary failure in name resolution|"
            r"name or service not known|nodename nor servname|getaddrinfo failed|network is unreachable|"
            r"http error 5\d\d|incompleteread|incomplete data|remote end closed|\bssl\b|"
            r"unable to download (webpage|api page|json metadata|video data)|m3u8|"
            r"did not get any data blocks",
        ),
    )
)

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")
_ERROR_PREFIX = re.compile(r"^\s*(ERROR:\s*)?(\[[\w:]+\]\s*)?([\w-]{11}:\s*)?")

EXIT_OK = 0
EXIT_FAILURES = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130


def _normalize(message: str) -> str:
    """Remove ANSI colors and the ``ERROR: [youtube] <id>:`` prefix (keeps every line)."""
    return _ERROR_PREFIX.sub("", _ANSI_ESCAPE.sub("", message).strip(), count=1)


def classify_error(message: str) -> ErrorKind:
    """Map a yt-dlp error message to an :class:`ErrorKind`.

    The prefix is removed first so that a video id (e.g. one containing "ssl") cannot
    trigger a pattern.
    """
    text = _normalize(message)
    for kind, pattern in _PATTERNS:
        if pattern.search(text):
            return kind
    return ErrorKind.UNKNOWN


def clean_message(message: str) -> str:
    """First line of a yt-dlp message, without colors and the ``ERROR: [youtube] <id>:`` prefix."""
    lines = _normalize(message).splitlines()
    return (lines[0].strip() if lines else "") or t("error.unknown")


class YtGrabError(Exception):
    """Base class for errors that end the program with a friendly message."""

    exit_code = EXIT_FAILURES


class UsageError(YtGrabError):
    """The user supplied invalid input (bad URL, bad flag value, ...)."""

    exit_code = EXIT_USAGE


class AuthConfigError(YtGrabError):
    """Authentication settings are invalid or cookies could not be loaded."""

    exit_code = EXIT_USAGE


class OutputDirectoryError(YtGrabError):
    """The target directory cannot be created or written to."""

    exit_code = EXIT_USAGE


class VideoError(YtGrabError):
    """A single video (or playlist) failed to be probed or downloaded."""

    def __init__(self, message: str, kind: ErrorKind | None = None) -> None:
        cleaned = clean_message(message)
        super().__init__(cleaned)
        self.kind = kind if kind is not None else classify_error(message)


class DownloadCancelledError(Exception):
    """A download stopped because the user interrupted the run (Ctrl+C)."""
