from pathlib import Path

import pytest

from ytgrab.auth import AuthConfig, BrowserSpec, parse_browser_spec, validate_cookies_file
from ytgrab.errors import AuthConfigError


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("firefox", BrowserSpec("firefox")),
        ("Chrome", BrowserSpec("chrome")),
        ("chrome:Profile 1", BrowserSpec("chrome", profile="Profile 1")),
        ("chromium+gnomekeyring:default", BrowserSpec("chromium", "default", "GNOMEKEYRING")),
        ("firefox:default::Work", BrowserSpec("firefox", "default", None, "Work")),
    ],
)
def test_parse_browser_spec(spec, expected):
    assert parse_browser_spec(spec) == expected


@pytest.mark.parametrize("spec", ["netscape", "", "chrome+nosuchkeyring"])
def test_parse_browser_spec_rejects_invalid(spec):
    with pytest.raises(AuthConfigError):
        parse_browser_spec(spec)


def test_browser_spec_round_trips_to_string():
    spec = BrowserSpec("chromium", "default", "BASICTEXT", "c")
    assert parse_browser_spec(str(spec)) == spec
    assert spec.as_ytdlp_tuple() == ("chromium", "default", "BASICTEXT", "c")


def test_validate_cookies_file(tmp_path: Path):
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    assert validate_cookies_file(str(cookies)) == cookies.resolve()


def test_validate_cookies_file_errors(tmp_path: Path):
    with pytest.raises(AuthConfigError, match="not found"):
        validate_cookies_file(tmp_path / "missing.txt")
    empty = tmp_path / "empty.txt"
    empty.touch()
    with pytest.raises(AuthConfigError, match="empty"):
        validate_cookies_file(empty)
    with pytest.raises(AuthConfigError, match="not found"):
        validate_cookies_file(tmp_path)  # a directory


def test_auth_config(tmp_path: Path):
    assert not AuthConfig().is_configured
    assert AuthConfig().describe() == "no authentication"
    cookies = tmp_path / "c.txt"
    cookies.write_text("x", encoding="utf-8")
    config = AuthConfig.from_options("firefox", str(cookies))
    assert config.is_configured
    assert "firefox" in config.describe() and "c.txt" in config.describe()
