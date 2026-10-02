"""Application workflow: resolve input → probe → choose quality & folder → download → report."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from ytgrab.auth import AuthConfig
from ytgrab.downloader import DEFAULT_WORKERS, DownloadJob, DownloadManager, DownloadReport, JobStatus
from ytgrab.environment import Environment
from ytgrab.errors import (
    EXIT_FAILURES,
    EXIT_INTERRUPTED,
    EXIT_OK,
    AuthConfigError,
    ErrorKind,
    OutputDirectoryError,
    UsageError,
    VideoError,
)
from ytgrab.formats import QualitySpec, collect_quality_options, default_height, resolve_quality
from ytgrab.gateway import LoadedCookies, MediaClient
from ytgrab.models import AudioOnly, Mode, PlaylistInfo, ProbeTarget, Selection, SubtitleOptions, VideoInfo
from ytgrab.options import DEFAULT_CONTAINER, DownloadSettings, build_download_params
from ytgrab.paths import default_download_dir, ensure_writable_directory, sanitize_component
from ytgrab.probe import ProbeFailure, Prober, ProbeResult, playlist_from_info
from ytgrab.progress import ProbeProgress, RichProgressReporter
from ytgrab.prompts import Prompter, render_quality_table
from ytgrab.retry import RetryPolicy
from ytgrab.urls import normalize_playlist_url, normalize_video_urls

ClientFactory = Callable[[LoadedCookies | None], MediaClient]
CookieLoader = Callable[[AuthConfig], LoadedCookies]

AUTH_HINT = (
    "Members-only, private and age-restricted videos need a signed-in YouTube account "
    "(with an active membership for members-only videos). Pass --cookies-from-browser BROWSER "
    "or --cookies FILE."
)


@dataclass(frozen=True)
class RunOptions:
    """Everything the user specified on the command line."""

    mode: Mode | None = None
    urls: tuple[str, ...] = ()
    output_dir: Path | None = None
    quality: QualitySpec | None = None
    audio_codec: str | None = None
    container: str = DEFAULT_CONTAINER
    subtitles: SubtitleOptions = field(default_factory=SubtitleOptions)
    auth: AuthConfig = field(default_factory=AuthConfig)
    jobs: int = DEFAULT_WORKERS
    overwrite: bool = False
    list_qualities: bool = False


class App:
    """Runs one ytgrab session. All I/O dependencies are injected for testability."""

    def __init__(
        self,
        options: RunOptions,
        *,
        prompter: Prompter,
        console: Console,
        environment: Environment,
        client_factory: ClientFactory,
        cookie_loader: CookieLoader,
        interactive: bool,
        retry: RetryPolicy | None = None,
    ) -> None:
        self._options = options
        self._prompter = prompter
        self._console = console
        self._env = environment
        self._client_factory = client_factory
        self._cookie_loader = cookie_loader
        self._interactive = interactive
        self._retry = retry
        self._auth = options.auth
        self._connected_client: MediaClient | None = None

    @property
    def _client(self) -> MediaClient:
        if self._connected_client is None:
            raise RuntimeError("not connected: call _connect() first")
        return self._connected_client

    # ------------------------------------------------------------------ workflow

    def run(self) -> int:
        """Execute the whole workflow and return the process exit code."""
        self._warn_about_environment()
        mode, urls = self._resolve_targets()
        self._connect(self._auth)

        playlist, targets = self._collect_targets(mode, urls)
        probe = self._recover_probe_auth(self._probe(targets), targets)
        self._report_probe_failures(probe.failures)
        if not probe.videos:
            self._console.print("[yellow]Nothing to download.")
            return self._exit_code(DownloadReport(), probe.failures)

        if self._options.list_qualities:
            options = collect_quality_options(probe.videos)
            self._console.print(render_quality_table(options, default_height(options), len(probe.videos)))
            return self._exit_code(DownloadReport(), probe.failures)

        selection = self._choose_selection(probe.videos)
        output_dir = self._choose_output_dir(playlist)
        if not self._confirm_plan(probe.videos, selection, output_dir):
            self._console.print("Aborted.")
            return EXIT_OK

        jobs = self._build_jobs(probe.videos, selection, output_dir, playlist)
        report = self._download(jobs)
        if not report.interrupted:
            report = self._recover_download_auth(report)

        self._print_summary(report, probe.failures, output_dir)
        return self._exit_code(report, probe.failures)

    @staticmethod
    def _exit_code(report: DownloadReport, probe_failures: Sequence[ProbeFailure]) -> int:
        if report.interrupted:
            return EXIT_INTERRUPTED
        if probe_failures or report.with_status(JobStatus.FAILED):
            return EXIT_FAILURES
        return EXIT_OK

    # ------------------------------------------------------------------ input & connection

    def _warn_about_environment(self) -> None:
        if not self._env.ffmpeg_available:
            self._console.print(
                "[yellow]⚠ ffmpeg was not found.[/] Without it, YouTube only offers single-file "
                "formats (usually up to 360p), audio cannot be converted and subtitles cannot be "
                "embedded. See the README for installation instructions."
            )
        if not self._env.js_runtimes:
            self._console.print(
                "[yellow]⚠ No JavaScript runtime (deno, node, bun or quickjs) was found.[/] "
                "YouTube may then only offer a few low-quality formats. Installing deno is "
                "recommended: https://deno.com"
            )

    def _resolve_targets(self) -> tuple[Mode, list[str]]:
        mode = self._options.mode or self._prompter.ask_mode()
        raw = list(self._options.urls) or self._prompter.ask_urls(mode)
        if mode is Mode.PLAYLIST:
            if len(raw) != 1:
                raise UsageError("Playlist mode takes exactly one playlist URL.")
            return mode, [normalize_playlist_url(raw[0])]
        return mode, normalize_video_urls(raw)

    def _connect(self, auth: AuthConfig) -> None:
        """(Re)create the client, loading cookies first if authentication is configured."""
        cookies = None
        if auth.is_configured:
            cookies = self._cookie_loader(auth)
            if cookies.youtube_cookie_count == 0:
                self._console.print(
                    f"[yellow]⚠ No YouTube cookies found in {escape(auth.describe())}. "
                    "Make sure you are signed in to YouTube there."
                )
            else:
                self._console.print(f"[dim]Using {escape(auth.describe())}.")
        self._connected_client = self._client_factory(cookies)
        self._auth = auth

    def _reauthenticate(self, reason: str) -> bool:
        """Ask the user for sign-in cookies and reconnect. True if a new client is ready."""
        if not self._interactive:
            return False
        if self._auth.is_configured:
            reason += f" The current {self._auth.describe()} did not grant access."
        while True:
            try:
                auth = self._prompter.ask_auth(reason)
                if auth is None:
                    return False
                self._connect(auth)
                return True
            except AuthConfigError as error:
                self._console.print(f"[red]{escape(str(error))}")

    # ------------------------------------------------------------------ probing

    def _collect_targets(
        self, mode: Mode, urls: Sequence[str]
    ) -> tuple[PlaylistInfo | None, list[ProbeTarget]]:
        if mode is Mode.VIDEO:
            return None, [ProbeTarget(url) for url in urls]
        playlist = self._fetch_playlist(urls[0])
        self._console.print(
            f"Playlist [b]{escape(playlist.title)}[/] contains {len(playlist.entries)} video(s)."
        )
        return playlist, list(playlist.entries)

    def _fetch_playlist(self, url: str) -> PlaylistInfo:
        try:
            info = self._extract_playlist(url)
        except VideoError as error:
            # YouTube reports private playlists as "does not exist" to signed-out users.
            maybe_private = error.kind is ErrorKind.UNAVAILABLE and not self._auth.is_configured
            if error.kind is not ErrorKind.AUTH_REQUIRED and not maybe_private:
                raise
            if not self._reauthenticate(f"Cannot open this playlist ({error}). If it is private, sign in."):
                raise
            info = self._extract_playlist(url)
        return playlist_from_info(info, url)

    def _extract_playlist(self, url: str) -> Mapping[str, Any]:
        with self._console.status("Fetching playlist…"):
            return self._client.extract_playlist(url)

    def _probe(self, targets: Sequence[ProbeTarget]) -> ProbeResult:
        with ProbeProgress(self._console, total=len(targets)) as progress:
            return Prober(self._client, retry=self._retry).probe(targets, on_done=progress.advance)

    def _recover_probe_auth(self, probe: ProbeResult, targets: Sequence[ProbeTarget]) -> ProbeResult:
        needs_auth = probe.failures_of_kind(ErrorKind.AUTH_REQUIRED)
        if not needs_auth or not self._reauthenticate(
            f"{len(needs_auth)} video(s) require sign-in (members-only, private or age-restricted)."
        ):
            return probe
        retried = self._probe([failure.target for failure in needs_auth])
        remaining = ProbeResult(probe.videos, [f for f in probe.failures if f not in needs_auth])
        return remaining.merge(retried, order=targets)

    def _report_probe_failures(self, failures: Sequence[ProbeFailure]) -> None:
        for failure in failures:
            self._console.print(
                f"[red]✘[/] {escape(failure.label)}: {escape(str(failure.error))} "
                f"[dim]({failure.error.kind.value})"
            )
        if any(f.error.kind is ErrorKind.AUTH_REQUIRED for f in failures):
            self._console.print(f"[dim]{AUTH_HINT}")

    # ------------------------------------------------------------------ choices

    def _choose_selection(self, videos: Sequence[VideoInfo]) -> Selection:
        if self._options.audio_codec:
            return AudioOnly(self._options.audio_codec)
        options = collect_quality_options(videos)
        if self._options.quality is None:
            return self._prompter.ask_quality(options, default_height(options), len(videos))
        selection = resolve_quality(self._options.quality, options)
        if selection.height is not None and selection.height not in {o.height for o in options}:
            self._console.print(
                f"[yellow]{selection.height}p is not offered; the closest lower quality is used."
            )
        return selection

    def _choose_output_dir(self, playlist: PlaylistInfo | None) -> Path:
        while True:
            directory = self._options.output_dir or self._prompter.ask_directory(default_download_dir())
            if playlist is not None:
                directory = directory / sanitize_component(playlist.title)
            try:
                return ensure_writable_directory(directory)
            except OutputDirectoryError as error:
                if not self._interactive or self._options.output_dir is not None:
                    raise
                self._console.print(f"[red]{escape(str(error))}")

    def _confirm_plan(self, videos: Sequence[VideoInfo], selection: Selection, output_dir: Path) -> bool:
        if isinstance(selection, AudioOnly):
            what = f"audio only ({selection.codec})"
        elif selection.height is None:
            what = "best available quality"
        else:
            what = f"{selection.height}p (or closest lower)"
        workers = min(self._options.jobs, len(videos))
        self._console.print(
            f"\nReady to download [b]{len(videos)}[/] video(s) as [b]{what}[/] into "
            f"[b]{escape(str(output_dir))}[/] using {workers} parallel download(s)."
        )
        return self._prompter.confirm("Start download?", default=True)

    # ------------------------------------------------------------------ downloading

    def _build_jobs(
        self,
        videos: Sequence[VideoInfo],
        selection: Selection,
        output_dir: Path,
        playlist: PlaylistInfo | None,
    ) -> list[DownloadJob]:
        settings = DownloadSettings(
            output_dir=output_dir,
            selection=selection,
            container=self._options.container,
            subtitles=self._options.subtitles,
            overwrite=self._options.overwrite,
        )
        playlist_size = len(playlist.entries) if playlist else None
        return [
            DownloadJob(
                video,
                build_download_params(
                    settings, video, ffmpeg_available=self._env.ffmpeg_available, playlist_size=playlist_size
                ),
            )
            for video in videos
        ]

    def _download(self, jobs: Sequence[DownloadJob]) -> DownloadReport:
        with RichProgressReporter(self._console, total_jobs=len(jobs)) as reporter:
            manager = DownloadManager(
                self._client, workers=self._options.jobs, retry=self._retry, reporter=reporter
            )
            report = manager.run(jobs)
        if report.interrupted:
            self._console.print("[yellow]Interrupted. Partial downloads are kept and resume next time.")
        return report

    def _recover_download_auth(self, report: DownloadReport) -> DownloadReport:
        needs_auth = report.failures_of_kind(ErrorKind.AUTH_REQUIRED)
        if not needs_auth or not self._reauthenticate(f"{len(needs_auth)} download(s) require sign-in."):
            return report
        retried = self._download([result.job for result in needs_auth])
        by_id = {result.video.id: result for result in retried.results}
        merged = [by_id.get(result.video.id, result) for result in report.results]
        return DownloadReport(merged, interrupted=retried.interrupted)

    def _print_summary(
        self, report: DownloadReport, probe_failures: Sequence[ProbeFailure], output_dir: Path
    ) -> None:
        counts = {status: len(report.with_status(status)) for status in JobStatus}
        table = Table.grid(padding=(0, 2))
        table.add_row("[green]Downloaded", str(counts[JobStatus.COMPLETED]))
        table.add_row("[cyan]Already present", str(counts[JobStatus.SKIPPED]))
        if counts[JobStatus.CANCELLED]:
            table.add_row("[yellow]Cancelled", str(counts[JobStatus.CANCELLED]))
        failed = counts[JobStatus.FAILED] + len(probe_failures)
        table.add_row("[red]Failed" if failed else "Failed", str(failed))
        self._console.print()
        self._console.print(table)
        self._console.print(f"Saved to: [b]{escape(str(output_dir))}")
        if report.failures_of_kind(ErrorKind.AUTH_REQUIRED):
            self._console.print(f"[dim]{AUTH_HINT}")
