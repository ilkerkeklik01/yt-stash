"""Parallel download execution with retries, cancellation and progress reporting."""

from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from ytgrab.concurrency import map_interruptible
from ytgrab.errors import DownloadCancelledError, ErrorKind, VideoError
from ytgrab.gateway import MediaClient
from ytgrab.models import ProgressEvent, VideoInfo
from ytgrab.retry import RetryPolicy, call_with_retry

DEFAULT_WORKERS = 3
MAX_WORKERS = 16


class JobStatus(Enum):
    COMPLETED = "downloaded"
    SKIPPED = "skipped (already downloaded)"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class DownloadJob:
    video: VideoInfo
    params: Mapping[str, Any]


@dataclass(frozen=True)
class JobResult:
    job: DownloadJob
    status: JobStatus
    path: Path | None = None
    error: VideoError | None = None

    @property
    def video(self) -> VideoInfo:
        return self.job.video


@dataclass
class DownloadReport:
    results: list[JobResult] = field(default_factory=list)
    interrupted: bool = False

    def with_status(self, status: JobStatus) -> list[JobResult]:
        return [r for r in self.results if r.status is status]

    def failures_of_kind(self, kind: ErrorKind) -> list[JobResult]:
        return [r for r in self.with_status(JobStatus.FAILED) if r.error is not None and r.error.kind is kind]


class ProgressReporter(Protocol):
    def job_started(self, video: VideoInfo) -> None: ...
    def job_progress(self, video: VideoInfo, event: ProgressEvent) -> None: ...
    def job_retrying(self, video: VideoInfo, attempt: int, delay: float, error: VideoError) -> None: ...
    def job_finished(self, result: JobResult) -> None: ...


class NullReporter:
    """Reporter that ignores every event (useful for tests and quiet mode)."""

    def job_started(self, video: VideoInfo) -> None:
        pass

    def job_progress(self, video: VideoInfo, event: ProgressEvent) -> None:
        pass

    def job_retrying(self, video: VideoInfo, attempt: int, delay: float, error: VideoError) -> None:
        pass

    def job_finished(self, result: JobResult) -> None:
        pass


class DownloadManager:
    """Downloads several videos concurrently.

    Each download runs in its own thread with its own yt-dlp instance; yt-dlp
    additionally fetches fragments of a single video concurrently. Ctrl+C sets a
    cancel flag that active downloads observe at their next progress update.
    """

    def __init__(
        self,
        client: MediaClient,
        *,
        workers: int = DEFAULT_WORKERS,
        retry: RetryPolicy | None = None,
        reporter: ProgressReporter | None = None,
    ) -> None:
        self._client = client
        self._workers = max(1, min(workers, MAX_WORKERS))
        self._retry = retry or RetryPolicy()
        self._reporter = reporter or NullReporter()
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self, jobs: Sequence[DownloadJob]) -> DownloadReport:
        """Run all jobs. A Ctrl+C is absorbed and reflected in the report."""
        finished: dict[int, JobResult] = {}

        def run_indexed(item: tuple[int, DownloadJob]) -> None:
            index, job = item
            finished[index] = self._run_job(job)

        interrupted = False
        try:
            map_interruptible(run_indexed, list(enumerate(jobs)), self._workers, on_abort=self.cancel)
        except KeyboardInterrupt:
            interrupted = True

        results = []
        for index, job in enumerate(jobs):
            result = finished.get(index) or JobResult(job, JobStatus.CANCELLED)
            if interrupted and result.status is JobStatus.FAILED:
                # Ctrl+C also reaches child processes (ffmpeg), failing them mid-merge.
                result = replace(result, status=JobStatus.CANCELLED)
            results.append(result)
        return DownloadReport(results, interrupted=interrupted)

    def _run_job(self, job: DownloadJob) -> JobResult:
        self._reporter.job_started(job.video)
        result = self._attempt(job)
        self._reporter.job_finished(result)
        return result

    def _attempt(self, job: DownloadJob) -> JobResult:
        video = job.video
        try:
            outcome = call_with_retry(
                lambda: self._client.download(
                    video.url,
                    job.params,
                    on_progress=lambda event: self._reporter.job_progress(video, event),
                    cancel_event=self._cancel,
                ),
                self._retry,
                self._cancel,
                on_retry=lambda attempt, delay, error: self._reporter.job_retrying(
                    video, attempt, delay, error
                ),
            )
        except DownloadCancelledError:
            return JobResult(job, JobStatus.CANCELLED)
        except VideoError as error:
            return JobResult(job, JobStatus.FAILED, error=error)
        except Exception as exc:  # an unexpected bug must not abort other downloads
            error = VideoError(f"{type(exc).__name__}: {exc}", ErrorKind.UNKNOWN)
            return JobResult(job, JobStatus.FAILED, error=error)

        status = JobStatus.SKIPPED if outcome.already_present else JobStatus.COMPLETED
        return JobResult(job, status, path=outcome.path)
