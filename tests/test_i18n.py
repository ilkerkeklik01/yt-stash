"""Tests of the message catalogs and the choice of language."""

from __future__ import annotations

import re
import string
from pathlib import Path

import pytest

from ytgrab import i18n
from ytgrab.auth import AuthConfig, BrowserSpec
from ytgrab.errors import ErrorKind, UsageError, VideoError
from ytgrab.i18n import (
    CATALOGS,
    en,
    normalize_language,
    resolve_language,
    set_language,
    system_language,
    t,
    tn,
)
from ytgrab.models import AudioOnly, Stage, SubtitleOptions, VideoQuality
from ytgrab.prompts import describe_selection, describe_subtitles
from ytgrab.urls import normalize_video_urls

SOURCE = Path(i18n.__file__).parent.parent
MARKUP = re.compile(r"\[/?[a-z]*\]")
# Keys built at run time: t(f"kind.{...}") and friends.
DYNAMIC_PREFIXES = ("kind.", "stage.", "place.", "hint.audio.", "hint.container.")


def fields(template: str) -> set[str]:
    return {name for _text, name, _spec, _conv in string.Formatter().parse(template) if name}


@pytest.mark.parametrize("code", [code for code in CATALOGS if code != "en"])
def test_catalog_matches_english(code):
    catalog = CATALOGS[code]
    assert catalog.keys() == en.MESSAGES.keys()
    for key, english in en.MESSAGES.items():
        assert catalog[key].strip(), key
        assert fields(catalog[key]) == fields(english), key
        assert MARKUP.findall(catalog[key]) == MARKUP.findall(english), key


def test_plural_keys_come_in_pairs():
    for key in en.MESSAGES:
        if key.endswith(".one"):
            assert key[: -len("one")] + "other" in en.MESSAGES
        if key.endswith(".other"):
            assert key[: -len("other")] + "one" in en.MESSAGES


def _source_text() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8") for path in SOURCE.rglob("*.py") if path.parent.name != "i18n"
    )


def test_every_key_used_in_the_code_exists():
    source = _source_text()
    for key in re.findall(r"""\bt\(\s*["']([\w.]+)["']""", source):
        assert key in en.MESSAGES, key
    for key in re.findall(r"""\btn\(\s*["']([\w.]+)["']""", source):
        assert f"{key}.one" in en.MESSAGES, key
    for kind in ErrorKind:
        assert f"kind.{kind.name.lower()}" in en.MESSAGES
    for stage in Stage:
        assert stage is Stage.PROCESSING or f"stage.{stage.value}" in en.MESSAGES


def test_every_key_is_used():
    source = _source_text()
    for key in en.MESSAGES:
        base = re.sub(r"\.(one|other)$", "", key)
        quoted = {f"{quote}{name}{quote}" for quote in "\"'" for name in (key, base)}
        assert key.startswith(DYNAMIC_PREFIXES) or any(q in source for q in quoted), key


def test_lookup_formats_and_falls_back_to_english(monkeypatch):
    assert t("urls.cannot_read", path="a.txt", reason="gone") == "Cannot read URL file 'a.txt': gone"
    monkeypatch.delitem(i18n.tr.MESSAGES, "menu.quit")
    set_language("tr")
    assert t("menu.quit") == "Quit"
    assert t("menu.videos") == "Video indir"
    with pytest.raises(ValueError):
        set_language("de")


def test_plural_forms():
    assert tn("count.video", 1) == "1 video"
    assert tn("count.video", 3) == "3 videos"
    set_language("tr")
    assert tn("count.video", 3) == "3 video"  # no plural after a number in Turkish


@pytest.mark.parametrize(
    ("tag", "code"),
    [
        ("tr", "tr"),
        ("tr_TR.UTF-8", "tr"),
        ("tr-TR", "tr"),
        ("TR", "tr"),
        ("en_GB", "en"),
        ("de_DE", None),
        ("C", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_language(tag, code):
    assert normalize_language(tag) == code


def test_resolve_language_takes_the_first_supported_candidate():
    assert resolve_language("tr", "en") == "tr"
    assert resolve_language(None, "de", "tr_TR.UTF-8") == "tr"
    assert resolve_language(None, "xx") == "en"


def test_system_language():
    assert system_language({"LANGUAGE": "de:tr", "LANG": "en_US"}, "linux") == "tr"
    assert system_language({"LC_ALL": "tr_TR.UTF-8", "LANG": "en_US.UTF-8"}, "linux") == "tr"
    assert system_language({"LC_ALL": "de_DE.UTF-8", "LANG": "tr_TR"}, "linux") is None  # LC_ALL decides
    assert system_language({"LC_ALL": "C"}, "linux") is None
    assert system_language({}, "linux") is None
    assert system_language({}, "win32", lambda: "tr") == "tr"
    assert system_language({"LANG": "en_US"}, "win32", lambda: "tr") == "en"  # e.g. Git Bash


def test_turkish_messages_from_pure_modules():
    set_language("tr")
    assert ErrorKind.UNAVAILABLE.label == "video kullanılamıyor"
    assert ErrorKind.UNAVAILABLE.value == "video unavailable"  # values stay English
    assert VideoError("ERROR: [youtube] abcdefghijk: Video unavailable").kind is ErrorKind.UNAVAILABLE
    assert AuthConfig().describe() == "oturum açılmadı"
    assert AuthConfig(browser=BrowserSpec("firefox")).describe() == "'firefox' tarayıcısının çerezleri"
    assert describe_selection(AudioOnly("mp3")) == "yalnızca ses (mp3)"
    assert describe_selection(VideoQuality(720)) == "720p (veya en yakın düşük kalite)"
    subtitles = SubtitleOptions(("tr", "en"), include_auto_generated=True, embed=True)
    assert describe_subtitles(subtitles) == "tr, en (videonun içinde, otomatik altyazılar dahil)"
    with pytest.raises(UsageError, match="Geçerli bir YouTube video URL'si değil"):
        normalize_video_urls(["nope"])
