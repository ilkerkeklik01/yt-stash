"""User-visible text in English and Turkish.

Every message lives in a catalog (:mod:`ytgrab.i18n.en`, :mod:`ytgrab.i18n.tr`) under a
dotted key and is looked up with :func:`t` when it is shown, so a language change from the
main menu applies at once. Templates are whole sentences with ``str.format`` placeholders:
Turkish attaches suffixes and orders words differently, so text is never glued together
from translated fragments.

The current language is process-wide state, like :mod:`gettext`'s. It is only changed on
the main thread (at start-up and from the main menu, while nothing downloads); worker
threads only read it.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Callable, Mapping

from ytgrab.i18n import en, tr

LANGUAGES = {"en": "English", "tr": "Türkçe"}  # names in their own language, never translated
DEFAULT_LANGUAGE = "en"

CATALOGS: dict[str, Mapping[str, str]] = {"en": en.MESSAGES, "tr": tr.MESSAGES}
_current = DEFAULT_LANGUAGE


def set_language(code: str) -> None:
    global _current
    if code not in LANGUAGES:
        raise ValueError(f"unsupported language: {code!r}")
    _current = code


def get_language() -> str:
    return _current


def t(key: str, **params: object) -> str:
    """The message ``key`` in the current language (English if it is not translated)."""
    template = CATALOGS[_current].get(key) or en.MESSAGES[key]
    return template.format(**params)


def tn(key: str, count: int, **params: object) -> str:
    """Like :func:`t`, choosing ``key.one`` or ``key.other`` by ``count`` (passed as ``{count}``)."""
    return t(f"{key}.one" if count == 1 else f"{key}.other", count=count, **params)


# ---------------------------------------------------------------------- language choice


def normalize_language(tag: str | None) -> str | None:
    """``"tr"`` for ``tr``, ``tr_TR.UTF-8`` or ``tr-TR``; ``None`` for unsupported languages."""
    if not tag:
        return None
    code = re.split(r"[._@-]", tag)[0].lower()
    return code if code in LANGUAGES else None


def resolve_language(*candidates: str | None) -> str:
    """The first supported language among ``candidates`` (highest priority first), else English."""
    for candidate in candidates:
        code = normalize_language(candidate)
        if code:
            return code
    return DEFAULT_LANGUAGE


def _windows_ui_language() -> str | None:
    """Language of the Windows user interface, e.g. ``"tr"``."""
    try:
        import ctypes

        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return None
    primary = lang_id & 0x3FF
    return {0x1F: "tr"}.get(primary)  # anything else means English


def system_language(
    environ: Mapping[str, str] = os.environ,
    platform: str = sys.platform,
    windows_ui_language: Callable[[], str | None] = _windows_ui_language,
) -> str | None:
    """The user's language from the variables gettext reads, or Windows' UI language.

    ``None`` when it is not supported (English is then used). ``LANGUAGE`` may list several
    languages (``de:tr``): the first supported one counts.
    """
    for entry in environ.get("LANGUAGE", "").split(":"):
        code = normalize_language(entry)
        if code:
            return code
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = environ.get(name)
        if value:
            return normalize_language(value)
    if platform == "win32":
        return windows_ui_language()
    return None
