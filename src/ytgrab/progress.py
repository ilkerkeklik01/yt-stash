"""Live terminal progress display built on rich (thread-safe)."""

from __future__ import annotations

import threading
from types import TracebackType

from rich.console import Console
from rich.filesize import decimal
from rich.markup import escape
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskID, TaskProgressColumn, TextColumn

from ytgrab.downloader import JobResult, JobStatus
from ytgrab.errors import VideoError
from ytgrab.i18n import t
from ytgrab.models import ProgressEvent, Stage, VideoInfo

_TITLE_WIDTH = 42


def shorten(text: str, width: int = _TITLE_WIDTH) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def _format_eta(seconds: int | None) -> str:
    if seconds is None:
        return "--:--"
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def describe_progress(event: ProgressEvent) -> str:
    """Human readable "12.3 MB/45.6 MB • 3.2 MB/s • ETA 00:12" text for an event."""
    if event.stage is Stage.PROCESSING:
        return t("progress.processing")
    size = decimal(event.downloaded_bytes)
    if event.total_bytes:
        size += f"/{decimal(int(event.total_bytes))}"
    parts = [t("progress.stage", stage=t(f"stage.{event.stage.value}"), size=size)]
    if event.speed:
        parts.append(f"{decimal(int(event.speed))}/s")
    if event.eta is not None:
        parts.append(t("progress.eta", eta=_format_eta(event.eta)))
    return " • ".join(parts)


class _BaseProgress:
    def __init__(self, console: Console) -> None:
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            BarColumn(bar_width=28),
            TaskProgressColumn(),
            TextColumn("[dim]{task.fields[detail]}"),
            console=console,
            transient=True,
        )

    def __enter__(self) -> _BaseProgress:
        self._progress.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._progress.stop()


class ProbeProgress(_BaseProgress):
    """Progress bar for the metadata probing phase."""

    def __init__(self, console: Console, total: int) -> None:
        super().__init__(console)
        self._task = self._progress.add_task(t("progress.fetching"), total=total, detail="")

    def advance(self, *_args: object) -> None:
        self._progress.advance(self._task)


class RichProgressReporter(_BaseProgress):
    """:class:`~ytgrab.downloader.ProgressReporter` with one bar per active download."""

    def __init__(self, console: Console, total_jobs: int) -> None:
        super().__init__(console)
        self._console = console
        self._lock = threading.Lock()
        self._tasks: dict[str, TaskID] = {}
        self._stages: dict[str, Stage] = {}
        self._overall = self._progress.add_task(
            f"[bold]{t('progress.overall')}",
            total=total_jobs,
            detail=t("progress.done", done=0, total=total_jobs),
        )
        self._total = total_jobs
        self._done = 0

    def job_started(self, video: VideoInfo) -> None:
        with self._lock:
            self._tasks[video.id] = self._progress.add_task(
                escape(shorten(video.title)), total=None, detail=t("progress.starting")
            )

    def job_progress(self, video: VideoInfo, event: ProgressEvent) -> None:
        with self._lock:
            task = self._tasks.get(video.id)
            if task is None:
                return
            if self._stages.get(video.id) != event.stage:
                # Video and audio streams are downloaded one after another: restart the bar.
                self._stages[video.id] = event.stage
                self._progress.reset(task, total=None)
            total = event.total_bytes if event.stage is not Stage.PROCESSING else None
            self._progress.update(
                task,
                total=total,
                completed=event.downloaded_bytes,
                detail=describe_progress(event),
            )

    def job_retrying(self, video: VideoInfo, attempt: int, delay: float, error: VideoError) -> None:
        self._console.print(
            f"[yellow]↻ {escape(shorten(video.title))}: {escape(str(error))} "
            f"{t('progress.retrying', delay=delay, attempt=attempt + 1)}"
        )

    def job_finished(self, result: JobResult) -> None:
        with self._lock:
            task = self._tasks.pop(result.video.id, None)
            self._stages.pop(result.video.id, None)
            if task is not None:
                self._progress.remove_task(task)
            self._done += 1
            self._progress.update(
                self._overall,
                completed=self._done,
                detail=t("progress.done", done=self._done, total=self._total),
            )
        self._console.print(_result_line(result))


def _result_line(result: JobResult) -> str:
    title = escape(shorten(result.video.title, 60))
    if result.status is JobStatus.COMPLETED:
        name = escape(result.path.name) if result.path else ""
        return f"[green]✔[/] {title} [dim]→ {name}"
    if result.status is JobStatus.SKIPPED:
        return f"[cyan]•[/] {title} [dim]{t('progress.already_downloaded')}"
    if result.status is JobStatus.CANCELLED:
        return f"[yellow]■[/] {title} [dim]{t('progress.cancelled')}"
    return f"[red]✘[/] {title}: {escape(str(result.error))}"
