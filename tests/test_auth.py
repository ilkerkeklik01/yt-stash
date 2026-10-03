from pathlib import Path

import pytest

from ytgrab.auth import (
    AuthConfig,
    BrowserSpec,
    parse_browser_spec,
    parse_pasted_cookies,
    validate_cookies_file,
)
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


SECRET = "AKfycb-secret-value"


@pytest.mark.parametrize(
    "pasted",
    [
        f"SID={SECRET}; HSID=abc; __Secure-3PAPISID=x/y=z",
        f"cookie: SID={SECRET};HSID=abc ; __Secure-3PAPISID=x/y=z;",
        f"Cookie: SID={SECRET};\n HSID=abc; __Secure-3P\nAPISID=x/y=z",  # wrapped, even inside a name
    ],
)
def test_pasted_cookie_header(pasted):
    cookies = parse_pasted_cookies(pasted)
    assert cookies.count == 3
    lines = cookies.netscape.splitlines()
    assert lines[0] == "# Netscape HTTP Cookie File"
    assert f".youtube.com\tTRUE\t/\tTRUE\t0\tSID\t{SECRET}" in lines
    assert ".youtube.com\tTRUE\t/\tTRUE\t0\t__Secure-3PAPISID\tx/y=z" in lines  # "=" inside a value


def test_pasted_cookies_txt_keeps_valid_entries_only():
    pasted = (
        "# Netscape HTTP Cookie File\n"
        f"#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t2147483647\tSID\t{SECRET}\r\n"
        ".youtube.com\tTRUE\t/\tTRUE\tsoon\tBAD\tvalue\n"  # invalid expiry: dropped, not printed
        "a broken\tline\n"
        ".youtube.com\tTRUE\t/\tFALSE\t\tPREF\tf6=8\n"
    )
    cookies = parse_pasted_cookies(pasted)
    assert cookies.count == 2
    assert "BAD" not in cookies.netscape and "broken" not in cookies.netscape


@pytest.mark.parametrize("pasted", ["", "   \n ", f"just text {SECRET}", "=novalue; =x", "a b=c"])
def test_unusable_paste_is_rejected_without_repeating_it(pasted):
    with pytest.raises(AuthConfigError) as excinfo:
        parse_pasted_cookies(pasted)
    assert SECRET not in str(excinfo.value)


def test_pasted_cookies_never_show_and_can_be_discarded():
    cookies = parse_pasted_cookies(f"SID={SECRET}")
    auth = AuthConfig(pasted=cookies)
    assert auth.is_configured
    assert SECRET not in repr(auth) and SECRET not in auth.describe()
    assert auth.describe() == "1 pasted cookie (for this download only)"
    assert auth != AuthConfig() and auth != AuthConfig(pasted=parse_pasted_cookies(f"SID={SECRET}"))
    cookies.discard()
    assert cookies.discarded and cookies.netscape == ""
