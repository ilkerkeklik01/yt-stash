"""Render the ``yt-stash`` command line that repeats an interactive run without questions."""

from __future__ import annotations

import shlex
import subprocess
import sys
from collections.abc import Sequence

from yt_stash.auth import AuthConfig
from yt_stash.downloader import DEFAULT_WORKERS
from yt_stash.models import AudioOnly, DownloadPlan, Mode
from yt_stash.options import DEFAULT_CONTAINER
from yt_stash.paths import display_path

# More URLs than this make the command unreadable; a placeholder is shown instead.
MAX_LISTED_URLS = 3


def _join(argv: Sequence[str]) -> str:
    if sys.platform == "win32":
        return subprocess.list2cmdline(argv)
    # Quoting "~" would stop the shell from expanding it, so only the rest is quoted.
    return " ".join("~/" + shlex.quote(arg[2:]) if arg.startswith("~/") else shlex.quote(arg) for arg in argv)


def equivalent_command(mode: Mode, urls: Sequence[str], plan: DownloadPlan, auth: AuthConfig) -> str:
    """The non-interactive command that downloads ``urls`` with exactly the choices of ``plan``."""
    argv = ["yt-stash", mode.value]
    argv += list(urls) if len(urls) <= MAX_LISTED_URLS else ["URL..."]

    if isinstance(plan.selection, AudioOnly):
        argv += ["-a", plan.selection.codec]
    else:
        height = plan.selection.height
        argv += ["-q", str(height) if height is not None else "best"]
        if plan.container != DEFAULT_CONTAINER:
            argv += ["--container", plan.container]
    argv += ["-o", display_path(plan.output_dir)]

    subtitles = plan.subtitles
    if subtitles.enabled:
        argv += ["--subs", ",".join(subtitles.languages)]
        if subtitles.include_auto_generated:
            argv.append("--auto-subs")
        if subtitles.embed:
            argv.append("--embed-subs")
    if plan.overwrite:
        argv.append("--overwrite")
    if plan.jobs != DEFAULT_WORKERS:
        argv += ["-j", str(plan.jobs)]
    if auth.browser:
        argv += ["--cookies-from-browser", str(auth.browser)]
    if auth.cookies_file:
        argv += ["--cookies", display_path(auth.cookies_file)]
    if auth.pasted:
        argv.append("--paste-cookies")  # asks again: pasted cookies are never stored
    argv.append("--yes")
    return _join(argv)
