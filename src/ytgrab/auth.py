"""Authentication settings for members-only, private and age-restricted videos.

YouTube does not allow password logins from third-party tools, so authentication works
through the cookies of a signed-in browser session: either read directly from a browser
profile, or from an exported Netscape ``cookies.txt`` file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from yt_dlp.cookies import SUPPORTED_BROWSERS, SUPPORTED_KEYRINGS

from ytgrab.errors import AuthConfigError
from ytgrab.paths import expand_path

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
        raise AuthConfigError(f"Invalid browser specification: '{spec}'.")
    name = match.group("name").strip().lower()
    if name not in SUPPORTED_BROWSERS:
        raise AuthConfigError(f"Unsupported browser '{name}'. Supported browsers: {', '.join(BROWSERS)}.")
    keyring = match.group("keyring")
    if keyring is not None:
        keyring = keyring.strip().upper()
        if keyring not in SUPPORTED_KEYRINGS:
            raise AuthConfigError(
                f"Unsupported keyring '{keyring}'. Supported: {', '.join(sorted(SUPPORTED_KEYRINGS))}."
            )
    return BrowserSpec(name, match.group("profile"), keyring, match.group("container"))


def validate_cookies_file(raw: str | Path) -> Path:
    """Check that ``raw`` points to a readable, non-empty file."""
    path = expand_path(raw)
    if not path.is_file():
        raise AuthConfigError(f"Cookies file not found: '{path}'.")
    try:
        if path.stat().st_size == 0:
            raise AuthConfigError(f"Cookies file is empty: '{path}'.")
        with path.open(encoding="utf-8", errors="replace"):
            pass
    except OSError as exc:
        raise AuthConfigError(f"Cannot read cookies file '{path}': {exc.strerror or exc}") from exc
    return path


@dataclass(frozen=True)
class AuthConfig:
    """Where to take login cookies from. Both sources may be combined."""

    browser: BrowserSpec | None = None
    cookies_file: Path | None = None

    @property
    def is_configured(self) -> bool:
        return self.browser is not None or self.cookies_file is not None

    def describe(self) -> str:
        parts = []
        if self.browser:
            parts.append(f"cookies from browser '{self.browser}'")
        if self.cookies_file:
            parts.append(f"cookies file '{self.cookies_file}'")
        return " + ".join(parts) or "no authentication"

    @classmethod
    def from_options(cls, browser: str | None, cookies_file: str | None) -> AuthConfig:
        return cls(
            browser=parse_browser_spec(browser) if browser else None,
            cookies_file=validate_cookies_file(cookies_file) if cookies_file else None,
        )
