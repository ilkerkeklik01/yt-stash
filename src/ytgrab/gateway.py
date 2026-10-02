"""The single gateway between ytgrab and yt-dlp's extraction/download API.

Everything else talks to the :class:`MediaClient` protocol, so it can be unit-tested
with a fake client and never touches the network.
"""

from __future__ import annotations

import io
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yt_dlp
from yt_dlp.cookies import CookieLoadError, load_cookies
from yt_dlp.utils import DownloadCancelled, YoutubeDLError

from ytgrab.auth import AuthConfig
from ytgrab.environment import Environment
from ytgrab.errors import AuthConfigError, DownloadCancelledError, VideoError
from ytgrab.models import ProgressEvent, Stage

ProgressCallback = Callable[[ProgressEvent], None]
LogCallback = Callable[[str], None]


@dataclass(frozen=True)
class DownloadOutcome:
    """Result of one successful download call."""

    path: Path | None
    already_present: bool = False  # the final file existed, nothing was transferred


class MediaClient(Protocol):
    """Operations the application needs from a YouTube backend."""

    def extract_playlist(self, url: str) -> Mapping[str, Any]:
        """Return the playlist's flat metadata (entries are not resolved)."""
        ...

    def extract_video(self, url: str) -> Mapping[str, Any]:
        """Return the metadata of a single video, including its formats."""
        ...

    def download(
        self,
        url: str,
        params: Mapping[str, Any],
        *,
        on_progress: ProgressCallback,
        cancel_event: threading.Event,
    ) -> DownloadOutcome:
        """Download one video (or detect that its final file already exists)."""
        ...


class _YtDlpLogger:
    """Routes yt-dlp output to ytgrab; errors are raised by yt-dlp and reported by us."""

    def __init__(self, on_debug: LogCallback | None = None) -> None:
        self._on_debug = on_debug

    def debug(self, msg: str) -> None:
        if self._on_debug:
            self._on_debug(msg)

    def info(self, msg: str) -> None:
        self.debug(msg)

    def warning(self, msg: str) -> None:
        self.debug(f"WARNING: {msg}")

    def error(self, msg: str) -> None:
        self.debug(msg)


@dataclass(frozen=True)
class LoadedCookies:
    """Cookies serialised in Netscape format, plus how many belong to YouTube."""

    text: str
    youtube_cookie_count: int


def load_auth_cookies(auth: AuthConfig, on_debug: LogCallback | None = None) -> LoadedCookies:
    """Read the configured cookies once, so parallel workers don't each hit the browser.

    Reading browser cookies can trigger OS keychain prompts and is slow; reading them
    once and handing every worker an in-memory copy also guarantees that yt-dlp never
    rewrites the user's own cookies.txt file.
    """
    browser = auth.browser.as_ytdlp_tuple() if auth.browser else None
    cookie_file = str(auth.cookies_file) if auth.cookies_file else None
    with yt_dlp.YoutubeDL({"quiet": True, "logger": _YtDlpLogger(on_debug)}) as ydl:
        try:
            jar = load_cookies(cookie_file, browser, ydl)
        except CookieLoadError as exc:
            cause = exc.__context__ or exc
            raise AuthConfigError(f"Could not load cookies ({auth.describe()}): {cause}") from exc

    buffer = io.StringIO()
    jar.save(buffer)
    youtube_count = sum(1 for cookie in jar if cookie.domain.lstrip(".").endswith("youtube.com"))
    return LoadedCookies(buffer.getvalue(), youtube_count)


def _stage_of(info: Mapping[str, Any]) -> Stage:
    if info.get("vcodec") == "none":
        return Stage.AUDIO
    if info.get("acodec") == "none":
        return Stage.VIDEO
    return Stage.FILE


def _final_path(info: Mapping[str, Any]) -> Path | None:
    downloads = info.get("requested_downloads") or []
    for candidate in (*(d.get("filepath") for d in reversed(downloads)), info.get("filepath")):
        if candidate:
            return Path(candidate)
    return None


class YtDlpClient:
    """:class:`MediaClient` implementation backed by the yt-dlp library."""

    def __init__(
        self,
        environment: Environment,
        cookies: LoadedCookies | None = None,
        on_debug: LogCallback | None = None,
    ) -> None:
        self._cookie_text = cookies.text if cookies else None
        self._base_params: dict[str, Any] = {
            "quiet": True,
            "noprogress": True,
            "no_color": True,
            "logger": _YtDlpLogger(on_debug),
            "socket_timeout": 30,
            "extractor_retries": 3,
        }
        if environment.js_runtimes:
            self._base_params["js_runtimes"] = environment.js_runtimes
        if environment.ffmpeg_location:
            self._base_params["ffmpeg_location"] = str(environment.ffmpeg_location)
        # YoutubeDL instances are not thread-safe: keep one extractor per thread.
        self._local = threading.local()

    def _new_ydl(self, extra: Mapping[str, Any] | None = None) -> yt_dlp.YoutubeDL:
        params = {**self._base_params, **(extra or {})}
        if self._cookie_text is not None:
            # A private in-memory copy per instance: yt-dlp writes cookies back on close.
            params["cookiefile"] = io.StringIO(self._cookie_text)
        return yt_dlp.YoutubeDL(params)

    def _thread_ydl(self) -> yt_dlp.YoutubeDL:
        ydl = getattr(self._local, "ydl", None)
        if ydl is None:
            ydl = self._local.ydl = self._new_ydl()
        return ydl

    def extract_playlist(self, url: str) -> Mapping[str, Any]:
        with self._new_ydl({"extract_flat": "in_playlist"}) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
            except YoutubeDLError as exc:
                raise VideoError(str(exc)) from exc
        if not info:
            raise VideoError(f"No playlist information returned for {url}")
        return info

    def extract_video(self, url: str) -> Mapping[str, Any]:
        try:
            # process=False: we only need the format list, not yt-dlp's format selection.
            info = self._thread_ydl().extract_info(url, download=False, process=False)
        except YoutubeDLError as exc:
            raise VideoError(str(exc)) from exc
        if not info:
            raise VideoError(f"No video information returned for {url}")
        return info

    def download(
        self,
        url: str,
        params: Mapping[str, Any],
        *,
        on_progress: ProgressCallback,
        cancel_event: threading.Event,
    ) -> DownloadOutcome:
        transferred = threading.Event()

        def progress_hook(data: dict[str, Any]) -> None:
            if cancel_event.is_set():
                raise DownloadCancelled()
            if data.get("status") not in ("downloading", "finished"):
                return
            if data.get("status") == "downloading":
                transferred.set()
            info = data.get("info_dict") or {}
            on_progress(
                ProgressEvent(
                    video_id=str(info.get("id", "")),
                    stage=_stage_of(info),
                    downloaded_bytes=int(data.get("downloaded_bytes") or 0),
                    total_bytes=data.get("total_bytes") or data.get("total_bytes_estimate"),
                    speed=data.get("speed"),
                    eta=data.get("eta"),
                )
            )

        def postprocessor_hook(data: dict[str, Any]) -> None:
            if data.get("status") == "started":
                info = data.get("info_dict") or {}
                on_progress(ProgressEvent(video_id=str(info.get("id", "")), stage=Stage.PROCESSING))

        hooked = {
            **params,
            "progress_hooks": [progress_hook],
            "postprocessor_hooks": [postprocessor_hook],
        }
        if cancel_event.is_set():
            raise DownloadCancelledError("Download cancelled.")
        with self._new_ydl(hooked) as ydl:
            try:
                info = ydl.extract_info(url, download=True)
            except DownloadCancelled as exc:
                raise DownloadCancelledError("Download cancelled.") from exc
            except YoutubeDLError as exc:
                raise VideoError(str(exc)) from exc
            except OSError as exc:
                raise VideoError(f"{exc.strerror or exc}") from exc
        # yt-dlp skips files that already exist without emitting "downloading" progress.
        return DownloadOutcome(_final_path(info or {}), already_present=not transferred.is_set())
