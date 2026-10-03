"""Shared test doubles. No test in the default suite touches the network."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from ytgrab import i18n
from ytgrab.auth import AuthConfig
from ytgrab.errors import VideoError
from ytgrab.gateway import DownloadOutcome
from ytgrab.models import (
    DownloadPlan,
    Mode,
    ProgressEvent,
    QualityOption,
    Selection,
    Stage,
    SubtitleOptions,
    VideoQuality,
)
from ytgrab.prompts import GoBack, ReviewAction


@pytest.fixture(autouse=True)
def english(tmp_path, monkeypatch):
    """Every test starts in English, whatever the machine's language or saved settings."""
    for name in ("YTGRAB_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("ytgrab.cli.system_language", lambda: None)
    monkeypatch.setattr("ytgrab.cli.config_path", lambda: tmp_path / "ytgrab-config.json")
    i18n.set_language("en")
    yield
    i18n.set_language("en")


def fmt(
    height: int | None,
    *,
    width: int | None = None,
    fps: float | None = 30,
    vcodec: str = "avc1",
    acodec: str = "none",
    ext: str = "mp4",
    hdr: bool = False,
) -> dict[str, Any]:
    """A minimal yt-dlp format dict."""
    return {
        "height": height,
        "width": width if width is not None else (height * 16 // 9 if height else None),
        "fps": fps,
        "vcodec": vcodec,
        "acodec": acodec,
        "ext": ext,
        "dynamic_range": "HDR10" if hdr else "SDR",
    }


AUDIO_FORMAT = {"vcodec": "none", "acodec": "mp4a", "ext": "m4a", "height": None}


def video_info(video_id: str, heights: Sequence[int] = (1080, 720), **extra: Any) -> dict[str, Any]:
    """A minimal yt-dlp video info dict."""
    return {
        "id": video_id,
        "title": f"Title {video_id}",
        "formats": [AUDIO_FORMAT, *(fmt(h) for h in heights)],
        "duration": 60,
        "channel": "Channel",
        "live_status": "not_live",
        **extra,
    }


def vid(n: int) -> str:
    """Deterministic 11-character video id."""
    return f"vid{n:08d}"


def url_of(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


DownloadBehaviour = Callable[[str, int], Path | None]  # (url, attempt) -> path, None = present, or raise


@dataclass
class FakeClient:
    """In-memory MediaClient. Configure per-URL infos, errors and download behaviour."""

    videos: dict[str, Any] = field(default_factory=dict)  # url -> info dict or VideoError
    playlist: Mapping[str, Any] | VideoError | None = None
    download_behaviour: DownloadBehaviour | None = None
    downloads: list[tuple[str, Mapping[str, Any]]] = field(default_factory=list)
    attempts: dict[str, int] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def extract_playlist(self, url: str) -> Mapping[str, Any]:
        if isinstance(self.playlist, VideoError):
            raise self.playlist
        assert self.playlist is not None, "no playlist configured"
        return self.playlist

    def extract_video(self, url: str) -> Mapping[str, Any]:
        value = self.videos.get(url)
        if value is None:
            raise VideoError("Video unavailable")
        if isinstance(value, Exception):
            raise value
        return value

    def download(
        self,
        url: str,
        params: Mapping[str, Any],
        *,
        on_progress: Callable[[ProgressEvent], None],
        cancel_event: threading.Event,
    ) -> DownloadOutcome:
        with self.lock:
            self.attempts[url] = self.attempts.get(url, 0) + 1
            attempt = self.attempts[url]
            self.downloads.append((url, params))
        on_progress(
            ProgressEvent(video_id=url[-11:], stage=Stage.VIDEO, downloaded_bytes=50, total_bytes=100)
        )
        if self.download_behaviour is None:
            return DownloadOutcome(Path(params["paths"]["home"]) / f"{url[-11:]}.mp4")
        path = self.download_behaviour(url, attempt)
        return DownloadOutcome(path, already_present=path is None)


@dataclass
class ScriptedPrompter:
    """Prompter returning pre-programmed answers and recording what was asked.

    ``review_actions`` are picked on the review screen one after another; once they are
    used up the download starts (or is cancelled when ``confirm_answer`` is False).
    Questions named in ``escape_at`` are left with Esc, in that order.
    """

    mode: Mode = Mode.VIDEO
    urls: list[str] = field(default_factory=list)
    quality: Selection | None = None  # None -> accept the default
    directory: Path | None = None
    confirm_answer: bool = True
    auth_answers: list[AuthConfig | None] = field(default_factory=list)
    review_actions: list[ReviewAction] = field(default_factory=list)
    container: str = "mkv"
    subtitles: SubtitleOptions = field(default_factory=SubtitleOptions)
    jobs: int = 1
    asked: list[str] = field(default_factory=list)
    quality_options: list[QualityOption] = field(default_factory=list)
    reviewed: list[DownloadPlan] = field(default_factory=list)
    review_targets: list[Path] = field(default_factory=list)
    escape_at: list[str] = field(default_factory=list)

    def _ask(self, question: str) -> None:
        """Record ``question``; press Esc on it if it is the next entry of ``escape_at``."""
        self.asked.append(question)
        if self.escape_at and self.escape_at[0] == question:
            self.escape_at.pop(0)
            raise GoBack

    def ask_mode(self) -> Mode:
        self._ask("mode")
        return self.mode

    def ask_urls(self, mode: Mode) -> list[str]:
        self._ask("urls")
        return self.urls

    def ask_quality(
        self,
        options: Sequence[QualityOption],
        default_height: int | None,
        video_count: int,
        current: Selection | None = None,
    ) -> Selection:
        self._ask("quality")
        self.quality_options = list(options)
        return self.quality or VideoQuality(default_height)

    def ask_directory(self, default: Path) -> Path:
        self._ask("directory")
        assert self.directory is not None
        return self.directory

    def ask_auth(self, reason: str) -> AuthConfig | None:
        self._ask("auth")
        return self.auth_answers.pop(0) if self.auth_answers else None

    def review(self, plan: DownloadPlan, *, video_count: int, target_dir: Path) -> ReviewAction:
        self._ask("review")
        self.reviewed.append(plan)
        self.review_targets.append(target_dir)
        if self.review_actions:
            return self.review_actions.pop(0)
        return ReviewAction.START if self.confirm_answer else ReviewAction.CANCEL

    def ask_container(self, current: str) -> str:
        self._ask("container")
        return self.container

    def ask_subtitles(self, current: SubtitleOptions, *, embed_possible: bool) -> SubtitleOptions:
        self._ask("subtitles")
        return self.subtitles

    def ask_overwrite(self, current: bool) -> bool:
        self._ask("overwrite")
        return not current

    def ask_jobs(self, current: int, video_count: int) -> int:
        self._ask("jobs")
        return self.jobs


@pytest.fixture
def fake_client() -> FakeClient:
    return FakeClient()
