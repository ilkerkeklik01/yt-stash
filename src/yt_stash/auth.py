"""Authentication settings for members-only, private and age-restricted videos.

YouTube does not allow password logins from third-party tools, so authentication works
through the cookies of a signed-in browser session: read directly from a browser profile,
from an exported Netscape ``cookies.txt`` file, or pasted into the terminal for one run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from yt_dlp.cookies import SUPPORTED_BROWSERS, SUPPORTED_KEYRINGS

from yt_stash.errors import AuthConfigError
from yt_stash.i18n import t, tn
from yt_stash.paths import expand_path

# Same syntax as yt-dlp: BROWSER[+KEYRING][:PROFILE][::CONTAINER]
_BROWSER_SPEC = re.compile(
    r"""(?x)
    (?P<name>[^+:]+)
    (?:\s*\+\s*(?P<keyring>[^:]+))?
    (?:\s*:\s*(?!:)(?P<profile>.+?))?
    (?:\s*::\s*(?P<container>.+))?
    """
)

BROWSERS = tuple(sorted(SUPPORTED_BROWSERS))

_NETSCAPE_HEADER = "# Netscape HTTP Cookie File\n"
_HTTPONLY_PREFIX = "#HttpOnly_"
_COOKIE_NAME = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")  # an RFC 6265 token


@dataclass(frozen=True)
class BrowserSpec:
    name: str
    profile: str | None = None
    keyring: str | None = None
    container: str | None = None

    def as_ytdlp_tuple(self) -> tuple[str, str | None, str | None, str | None]:
        return (self.name, self.profile, self.keyring, self.container)

    def __str__(self) -> str:
        text = self.name
        if self.keyring:
            text += f"+{self.keyring}"
        if self.profile:
            text += f":{self.profile}"
        if self.container:
            text += f"::{self.container}"
        return text


def parse_browser_spec(spec: str) -> BrowserSpec:
    """Parse ``BROWSER[+KEYRING][:PROFILE][::CONTAINER]``, e.g. ``firefox`` or ``chrome:Profile 1``."""
    match = _BROWSER_SPEC.fullmatch(spec.strip())
    if match is None:
        raise AuthConfigError(t("auth.invalid_spec", spec=spec))
    name = match.group("name").strip().lower()
    if name not in SUPPORTED_BROWSERS:
        raise AuthConfigError(t("auth.unsupported_browser", name=name, supported=", ".join(BROWSERS)))
    keyring = match.group("keyring")
    if keyring is not None:
        keyring = keyring.strip().upper()
        if keyring not in SUPPORTED_KEYRINGS:
            supported = ", ".join(sorted(SUPPORTED_KEYRINGS))
            raise AuthConfigError(t("auth.unsupported_keyring", keyring=keyring, supported=supported))
    return BrowserSpec(name, match.group("profile"), keyring, match.group("container"))


def validate_cookies_file(raw: str | Path) -> Path:
    """Check that ``raw`` points to a readable, non-empty file."""
    path = expand_path(raw)
    if not path.is_file():
        raise AuthConfigError(t("auth.cookies_not_found", path=path))
    try:
        if path.stat().st_size == 0:
            raise AuthConfigError(t("auth.cookies_empty", path=path))
        with path.open(encoding="utf-8", errors="replace"):
            pass
    except OSError as exc:
        raise AuthConfigError(t("auth.cookies_unreadable", path=path, reason=exc.strerror or exc)) from exc
    return path


class PastedCookies:
    """Cookies pasted into the terminal, as Netscape ``cookies.txt`` text.

    They exist only in memory and are used for one run: :meth:`discard` drops them when the
    run ends. Their text never appears in ``repr`` (tracebacks, debug output). Python cannot
    wipe a string's memory; discarding removes the last reference so it can be freed.
    """

    def __init__(self, netscape: str, count: int) -> None:
        self._netscape = netscape
        self.count = count

    @property
    def netscape(self) -> str:
        return self._netscape

    @property
    def discarded(self) -> bool:
        return not self._netscape

    def discard(self) -> None:
        self._netscape = ""

    def __repr__(self) -> str:
        return f"PastedCookies(count={self.count}, discarded={self.discarded})"


def _netscape_line(line: str) -> str | None:
    """``line`` if it is a valid ``cookies.txt`` entry, else ``None``."""
    fields = line.removeprefix(_HTTPONLY_PREFIX).split("\t")
    if len(fields) != 7 or not fields[0] or not _COOKIE_NAME.fullmatch(fields[5]):
        return None
    expires = fields[4]
    # Bounded: an absurd expiry makes http.cookiejar fail with the whole line (value included).
    return line if not expires or re.fullmatch(r"[0-9]{1,15}(\.[0-9]{1,9})?", expires) else None


def filter_cookie_file_text(text: str) -> str:
    """Keep only comments, blank lines and valid entries of a ``cookies.txt`` file.

    yt-dlp prints every line it cannot parse, with its cookie value, straight to stderr
    (ignoring ``quiet``), so malformed lines are dropped before it ever sees them.
    """
    kept = []
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        is_comment = line.startswith("#") and not line.startswith(_HTTPONLY_PREFIX)
        if not line.strip() or is_comment or _netscape_line(line):
            kept.append(line)
    return "\n".join(kept) + "\n"


def parse_pasted_cookies(text: str) -> PastedCookies:
    """Cookies from pasted text: a browser's ``Cookie`` header or a ``cookies.txt`` file's content.

    A header (``SID=…; HSID=…``, optionally starting with ``cookie:``) is taken as the
    cookies of ``.youtube.com``. Lines of a ``cookies.txt`` that are not valid entries are
    skipped here, so yt-dlp never prints them (with their values) as warnings.

    Raises:
        AuthConfigError: if nothing usable was pasted. The message never repeats the input.
    """
    text = text.strip()
    if not text:
        raise AuthConfigError(t("auth.paste_empty"))
    lines = text.splitlines()
    if any("\t" in line for line in lines):
        entries = [line for line in (line.strip(" \r") for line in lines) if _netscape_line(line)]
    else:
        # A header wrapped onto several lines may be split anywhere, even inside a value.
        header = re.sub(r"^cookie:\s*", "", "".join(line.strip() for line in lines), flags=re.IGNORECASE)
        pairs = (part.strip().partition("=") for part in header.split(";"))
        entries = [
            f".youtube.com\tTRUE\t/\tTRUE\t0\t{name}\t{value.strip()}"
            for name, equals, value in pairs
            if equals and _COOKIE_NAME.fullmatch(name)
        ]
    if not entries:
        raise AuthConfigError(t("auth.paste_invalid"))
    return PastedCookies(_NETSCAPE_HEADER + "\n".join(entries) + "\n", len(entries))


@dataclass(frozen=True)
class AuthConfig:
    """Where to take login cookies from. Browser and file may be combined; pasted cookies stand alone."""

    browser: BrowserSpec | None = None
    cookies_file: Path | None = None
    pasted: PastedCookies | None = None  # compared by identity: every paste is a new sign-in

    @property
    def is_configured(self) -> bool:
        return self.browser is not None or self.cookies_file is not None or self.pasted is not None

    def describe(self) -> str:
        parts = []
        if self.browser:
            parts.append(t("auth.browser", browser=self.browser))
        if self.cookies_file:
            parts.append(t("auth.file", path=self.cookies_file))
        if self.pasted:
            parts.append(tn("auth.pasted", self.pasted.count))
        return " + ".join(parts) or t("auth.none")

    @classmethod
    def from_options(cls, browser: str | None, cookies_file: str | None) -> AuthConfig:
        return cls(
            browser=parse_browser_spec(browser) if browser else None,
            cookies_file=validate_cookies_file(cookies_file) if cookies_file else None,
        )
