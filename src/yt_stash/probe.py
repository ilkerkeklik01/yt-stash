"""Fetch video metadata (available qualities) for many URLs in parallel."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from yt_stash.concurrency import map_interruptible
from yt_stash.errors import DownloadCancelledError, ErrorKind, VideoError, strip_control
from yt_stash.formats import resolutions_from_formats
from yt_stash.gateway import MediaClient
from yt_stash.i18n import t
from yt_stash.models import PlaylistInfo, ProbeTarget, VideoInfo
from yt_stash.retry import RetryPolicy, call_with_retry
from yt_stash.urls import canonical_video_url

DEFAULT_PROBE_WORKERS = 8


@dataclass(frozen=True)
class ProbeFailure:
    target: ProbeTarget
    error: VideoError

    @property
    def label(self) -> str:
        return self.target.title or self.target.url


@dataclass
class ProbeResult:
    videos: list[VideoInfo] = field(default_factory=list)
    failures: list[ProbeFailure] = field(default_factory=list)

    def failures_of_kind(self, kind: ErrorKind) -> list[ProbeFailure]:
        return [f for f in self.failures if f.error.kind is kind]

    def merge(self, other: ProbeResult, order: Sequence[ProbeTarget]) -> ProbeResult:
        """Combine two results; videos are sorted by their position in ``order``."""
        position = {target.url: index for index, target in enumerate(order)}
        videos = sorted([*self.videos, *other.videos], key=lambda v: position.get(v.url, len(position)))
        return ProbeResult(videos, [*self.failures, *other.failures])


def playlist_from_info(info: Mapping[str, Any], url: str) -> PlaylistInfo:
    """Convert yt-dlp's flat playlist metadata into a :class:`PlaylistInfo`."""
    targets: list[ProbeTarget] = []
    for position, entry in enumerate(info.get("entries") or [], start=1):
        if not entry or not entry.get("id"):
            continue  # yt-dlp yields None for entries it could not parse
        targets.append(
            ProbeTarget(
                url=canonical_video_url(entry["id"]),
                title=strip_control(entry["title"]) if isinstance(entry.get("title"), str) else None,
                playlist_index=entry.get("playlist_index") or position,
            )
        )
    return PlaylistInfo(
        id=str(info.get("id") or ""),
        title=strip_control(str(info.get("title") or info.get("id") or url)),
        entries=tuple(targets),
    )


def video_from_info(info: Mapping[str, Any], target: ProbeTarget) -> VideoInfo:
    """Convert yt-dlp's video metadata into a :class:`VideoInfo`.

    Raises:
        VideoError: for live streams that are still running or haven't started.
    """
    live_status = info.get("live_status")
    if live_status == "is_live":
        raise VideoError(t("error.live_in_progress"), ErrorKind.LIVE_IN_PROGRESS)
    if live_status == "is_upcoming":
        raise VideoError(t("error.upcoming"), ErrorKind.NOT_YET_AVAILABLE)

    duration = info.get("duration")
    return VideoInfo(
        id=str(info["id"]),
        title=strip_control(str(info.get("title") or target.title or info["id"])),
        url=target.url,
        resolutions=resolutions_from_formats(info.get("formats") or []),
        duration=int(duration) if isinstance(duration, (int, float)) else None,
        channel=strip_control(str(ch)) if (ch := info.get("channel") or info.get("uploader")) else None,
        playlist_index=target.playlist_index,
    )


class Prober:
    """Probes many videos concurrently; metadata requests are I/O bound."""

    def __init__(
        self,
        client: MediaClient,
        workers: int = DEFAULT_PROBE_WORKERS,
        retry: RetryPolicy | None = None,
    ) -> None:
        self._client = client
        self._workers = max(1, workers)
        self._retry = retry or RetryPolicy()
        self._cancel = threading.Event()

    def probe(
        self,
        targets: Sequence[ProbeTarget],
        on_done: Callable[[ProbeTarget], None] | None = None,
    ) -> ProbeResult:
        """Probe every target; failures are collected, never raised. Order is preserved.

        Transient errors (network, HTTP 429) are retried. On Ctrl+C, KeyboardInterrupt is
        raised immediately without waiting for in-flight requests.
        """

        def probe_one(target: ProbeTarget) -> VideoInfo | ProbeFailure:
            try:
                info = call_with_retry(
                    lambda: self._client.extract_video(target.url), self._retry, self._cancel
                )
                return video_from_info(info, target)
            except DownloadCancelledError:
                return ProbeFailure(target, VideoError(t("error.cancelled"), ErrorKind.UNKNOWN))
            except VideoError as exc:
                return ProbeFailure(target, exc)
            except Exception as exc:  # never let one odd video abort the whole batch
                return ProbeFailure(target, VideoError(str(exc), ErrorKind.UNKNOWN))
            finally:
                if on_done:
                    on_done(target)

        result = ProbeResult()
        outcomes = map_interruptible(
            probe_one, targets, self._workers, on_abort=self._cancel.set, wait_on_abort=False
        )
        for outcome in outcomes:
            if isinstance(outcome, VideoInfo):
                result.videos.append(outcome)
            else:
                result.failures.append(outcome)
        return result
