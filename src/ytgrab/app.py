"""Application workflow: resolve input → probe → choose quality & folder → download → report."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from ytgrab.auth import AuthConfig
from ytgrab.commandline import MAX_LISTED_URLS, equivalent_command
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
from ytgrab.i18n import t, tn
from ytgrab.models import (
    AudioOnly,
    DownloadPlan,
    Mode,
    PlaylistInfo,
    ProbeTarget,
    Selection,
    SubtitleOptions,
    VideoInfo,
)
from ytgrab.options import DEFAULT_CONTAINER, DownloadSettings, build_download_params
from ytgrab.paths import default_download_dir, display_path, ensure_writable_directory, sanitize_component
from ytgrab.probe import ProbeFailure, Prober, ProbeResult, playlist_from_info
from ytgrab.progress import ProbeProgress, RichProgressReporter
from ytgrab.prompts import GoBack, Prompter, ReviewAction, describe_selection, render_quality_table
from ytgrab.retry import RetryPolicy
from ytgrab.urls import normalize_playlist_url, normalize_video_urls

ClientFactory = Callable[[LoadedCookies | None], MediaClient]
CookieLoader = Callable[[AuthConfig], LoadedCookies]


def environment_warnings(environment: Environment) -> list[str]:
    """Rich-markup warnings about missing external programs."""
    warnings = []
    if not environment.ffmpeg_available:
        warnings.append(t("app.warn_ffmpeg"))
    if not environment.js_runtimes:
        warnings.append(t("app.warn_js"))
    return warnings


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
    """Runs one ytgrab session. All I/O dependencies are injected for testability.

    :class:`~ytgrab.prompts.GoBack` raised by a question that has no previous step here
    (link, quality, the review screen itself) leaves :meth:`run`: the caller goes back.
    """

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
        check_environment: bool = True,
    ) -> None:
        self._options = options
        self._prompter = prompter
        self._console = console
        self._env = environment
        self._client_factory = client_factory
        self._cookie_loader = cookie_loader
        self._interactive = interactive
        self._retry = retry
        self._check_environment = check_environment
        self._auth = options.auth
        self._connected_client: MediaClient | None = None

    @property
    def auth(self) -> AuthConfig:
        """The sign-in used in the end, including one the user entered during the run."""
        return self._auth

    @property
    def _client(self) -> MediaClient:
        if self._connected_client is None:
            raise RuntimeError("not connected: call _connect() first")
        return self._connected_client

    # ------------------------------------------------------------------ workflow

    def run(self) -> int:
        """Execute the whole workflow and return the process exit code."""
        if self._check_environment:
            for warning in environment_warnings(self._env):
                self._console.print(warning)
        mode, urls = self._resolve_targets()
        self._connect(self._auth)

        playlist, targets = self._collect_targets(mode, urls)
        probe = self._recover_probe_auth(self._probe(targets), targets)
        self._report_probe_failures(probe.failures)
        if not probe.videos:
            self._console.print(f"[yellow]{t('app.nothing_to_download')}")
            return self._exit_code(DownloadReport(), probe.failures)

        if self._options.list_qualities:
            options = collect_quality_options(probe.videos)
            self._console.print(render_quality_table(options, default_height(options), len(probe.videos)))
            return self._exit_code(DownloadReport(), probe.failures)

        plan = self._review_plan(probe.videos, self._initial_plan(probe.videos, playlist), playlist)
        if plan is None:
            self._console.print(t("cancelled"))
            return EXIT_OK

        output_dir = self._target_dir(plan.output_dir, playlist)
        jobs = self._build_jobs(probe.videos, plan, output_dir, playlist)
        report = self._download(jobs, plan.jobs)
        if not report.interrupted:
            report = self._recover_download_auth(report, plan.jobs)

        self._print_summary(report, probe.failures, output_dir)
        if self._interactive and not report.interrupted:
            self._print_equivalent_command(mode, urls, plan)
        return self._exit_code(report, probe.failures)

    @staticmethod
    def _exit_code(report: DownloadReport, probe_failures: Sequence[ProbeFailure]) -> int:
        if report.interrupted:
            return EXIT_INTERRUPTED
        if probe_failures or report.with_status(JobStatus.FAILED):
            return EXIT_FAILURES
        return EXIT_OK

    # ------------------------------------------------------------------ input & connection

    def _resolve_targets(self) -> tuple[Mode, list[str]]:
        mode = self._options.mode or self._prompter.ask_mode()
        raw = list(self._options.urls) or self._prompter.ask_urls(mode)
        if mode is Mode.PLAYLIST:
            if len(raw) != 1:
                raise UsageError(t("app.playlist_one_url"))
            return mode, [normalize_playlist_url(raw[0])]
        return mode, normalize_video_urls(raw)

    def _connect(self, auth: AuthConfig) -> None:
        """(Re)create the client, loading cookies first if authentication is configured."""
        cookies = None
        if auth.is_configured:
            cookies = self._cookie_loader(auth)
            if cookies.youtube_cookie_count == 0:
                self._console.print(f"[yellow]{t('app.no_cookies', auth=escape(auth.describe()))}")
            else:
                self._console.print(f"[dim]{t('app.using_auth', auth=escape(auth.describe()))}")
        self._connected_client = self._client_factory(cookies)
        self._auth = auth

    def _reauthenticate(self, reason: str) -> bool:
        """Ask the user for sign-in cookies and reconnect. True if a new client is ready."""
        if not self._interactive:
            return False
        if self._auth.is_configured:
            reason = t("app.auth_did_not_help", reason=reason, auth=self._auth.describe())
        while True:
            try:
                auth = self._prompter.ask_auth(reason)
                if auth is None:
                    return False
                self._connect(auth)
                return True
            except GoBack:  # Esc means the same as "Don't sign in"
                return False
            except AuthConfigError as error:
                self._console.print(f"[red]{escape(str(error))}")

    # ------------------------------------------------------------------ probing

    def _collect_targets(
        self, mode: Mode, urls: Sequence[str]
    ) -> tuple[PlaylistInfo | None, list[ProbeTarget]]:
        if mode is Mode.VIDEO:
            return None, [ProbeTarget(url) for url in urls]
        playlist = self._fetch_playlist(urls[0])
        self._console.print(tn("app.playlist_contains", len(playlist.entries), title=escape(playlist.title)))
        return playlist, list(playlist.entries)

    def _fetch_playlist(self, url: str) -> PlaylistInfo:
        try:
            info = self._extract_playlist(url)
        except VideoError as error:
            # YouTube reports private playlists as "does not exist" to signed-out users.
            maybe_private = error.kind is ErrorKind.UNAVAILABLE and not self._auth.is_configured
            if error.kind is not ErrorKind.AUTH_REQUIRED and not maybe_private:
                raise
            if not self._reauthenticate(t("app.playlist_private", error=error)):
                raise
            info = self._extract_playlist(url)
        return playlist_from_info(info, url)

    def _extract_playlist(self, url: str) -> Mapping[str, Any]:
        with self._console.status(t("app.fetching_playlist")):
            return self._client.extract_playlist(url)

    def _probe(self, targets: Sequence[ProbeTarget]) -> ProbeResult:
        with ProbeProgress(self._console, total=len(targets)) as progress:
            return Prober(self._client, retry=self._retry).probe(targets, on_done=progress.advance)

    def _recover_probe_auth(self, probe: ProbeResult, targets: Sequence[ProbeTarget]) -> ProbeResult:
        needs_auth = probe.failures_of_kind(ErrorKind.AUTH_REQUIRED)
        if not needs_auth or not self._reauthenticate(tn("app.videos_need_sign_in", len(needs_auth))):
            return probe
        retried = self._probe([failure.target for failure in needs_auth])
        remaining = ProbeResult(probe.videos, [f for f in probe.failures if f not in needs_auth])
        return remaining.merge(retried, order=targets)

    def _report_probe_failures(self, failures: Sequence[ProbeFailure]) -> None:
        for failure in failures:
            self._console.print(
                f"[red]✘[/] {escape(failure.label)}: {escape(str(failure.error))} "
                f"[dim]({failure.error.kind.label})"
            )
        if any(f.error.kind is ErrorKind.AUTH_REQUIRED for f in failures):
            self._console.print(f"[dim]{t('app.auth_hint')}")

    # ------------------------------------------------------------------ choices

    def _initial_plan(self, videos: Sequence[VideoInfo], playlist: PlaylistInfo | None) -> DownloadPlan:
        """Settings from the command line; quality and folder are asked if they were not given."""
        quality_asked = self._options.quality is None and not self._options.audio_codec
        while True:
            selection = self._choose_selection(videos)
            try:
                output_dir = self._choose_output_dir(playlist)
            except GoBack:
                if quality_asked:
                    continue  # Esc on the folder question returns to the quality question
                raise
            return DownloadPlan(
                selection=selection,
                output_dir=output_dir,
                container=self._options.container,
                subtitles=self._options.subtitles,
                overwrite=self._options.overwrite,
                jobs=self._options.jobs,
            )

    def _choose_selection(self, videos: Sequence[VideoInfo]) -> Selection:
        if self._options.audio_codec:
            return AudioOnly(self._options.audio_codec)
        if self._options.quality is None:
            return self._ask_selection(videos)
        options = collect_quality_options(videos)
        selection = resolve_quality(self._options.quality, options)
        if selection.height is not None and selection.height not in {o.height for o in options}:
            self._console.print(f"[yellow]{t('app.quality_not_offered', height=selection.height)}")
        return selection

    def _ask_selection(self, videos: Sequence[VideoInfo], current: Selection | None = None) -> Selection:
        options = collect_quality_options(videos)
        return self._prompter.ask_quality(options, default_height(options), len(videos), current)

    @staticmethod
    def _target_dir(output_dir: Path, playlist: PlaylistInfo | None) -> Path:
        """Where the files go: playlists get a subfolder named after them."""
        return output_dir / sanitize_component(playlist.title) if playlist else output_dir

    def _choose_output_dir(self, playlist: PlaylistInfo | None, current: Path | None = None) -> Path:
        """The folder from ``--output`` or asked, once its target is known to be writable.

        With ``current`` (a change on the review screen) the folder is always asked.
        """
        flag = self._options.output_dir if current is None else None
        while True:
            directory = flag or self._prompter.ask_directory(current or default_download_dir())
            try:
                ensure_writable_directory(self._target_dir(directory, playlist))
                return directory
            except OutputDirectoryError as error:
                if not self._interactive or flag is not None:
                    raise
                self._console.print(f"[red]{escape(str(error))}")

    def _review_plan(
        self, videos: Sequence[VideoInfo], plan: DownloadPlan, playlist: PlaylistInfo | None
    ) -> DownloadPlan | None:
        """Let the user change any setting before downloading. ``None`` if they cancel."""
        count = len(videos)
        prompter = self._prompter
        changes: dict[ReviewAction, Callable[[DownloadPlan], DownloadPlan]] = {
            ReviewAction.QUALITY: lambda p: replace(p, selection=self._ask_selection(videos, p.selection)),
            ReviewAction.DIRECTORY: lambda p: replace(
                p, output_dir=self._choose_output_dir(playlist, p.output_dir)
            ),
            ReviewAction.CONTAINER: lambda p: replace(p, container=prompter.ask_container(p.container)),
            ReviewAction.SUBTITLES: lambda p: replace(
                p,
                subtitles=prompter.ask_subtitles(
                    p.subtitles,
                    embed_possible=self._env.ffmpeg_available and not isinstance(p.selection, AudioOnly),
                ),
            ),
            ReviewAction.OVERWRITE: lambda p: replace(p, overwrite=prompter.ask_overwrite(p.overwrite)),
            ReviewAction.JOBS: lambda p: replace(p, jobs=prompter.ask_jobs(p.jobs, count)),
        }
        while True:
            target = self._target_dir(plan.output_dir, playlist)
            action = prompter.review(plan, video_count=count, target_dir=target)
            if action is ReviewAction.START:
                # The review menu disappears once answered; keep a record of what was started.
                started = t(
                    "app.downloading",
                    videos=tn("count.video", count),
                    quality=describe_selection(plan.selection),
                    path=escape(display_path(target)),
                    jobs=min(plan.jobs, count),
                )
                self._console.print(f"\n{started}")
                return plan
            if action is ReviewAction.CANCEL:
                return None
            # Esc while changing a setting keeps its value and returns to the review screen.
            with suppress(GoBack):
                plan = changes[action](plan)

    # ------------------------------------------------------------------ downloading

    def _build_jobs(
        self,
        videos: Sequence[VideoInfo],
        plan: DownloadPlan,
        output_dir: Path,
        playlist: PlaylistInfo | None,
    ) -> list[DownloadJob]:
        settings = DownloadSettings(
            output_dir=output_dir,
            selection=plan.selection,
            container=plan.container,
            subtitles=plan.subtitles,
            overwrite=plan.overwrite,
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

    def _download(self, jobs: Sequence[DownloadJob], workers: int) -> DownloadReport:
        with RichProgressReporter(self._console, total_jobs=len(jobs)) as reporter:
            manager = DownloadManager(self._client, workers=workers, retry=self._retry, reporter=reporter)
            report = manager.run(jobs)
        if report.interrupted:
            self._console.print(f"[yellow]{t('app.interrupted')}")
        return report

    def _recover_download_auth(self, report: DownloadReport, workers: int) -> DownloadReport:
        needs_auth = report.failures_of_kind(ErrorKind.AUTH_REQUIRED)
        if not needs_auth or not self._reauthenticate(tn("app.downloads_need_sign_in", len(needs_auth))):
            return report
        retried = self._download([result.job for result in needs_auth], workers)
        by_id = {result.video.id: result for result in retried.results}
        merged = [by_id.get(result.video.id, result) for result in report.results]
        return DownloadReport(merged, interrupted=retried.interrupted)

    def _print_summary(
        self, report: DownloadReport, probe_failures: Sequence[ProbeFailure], output_dir: Path
    ) -> None:
        counts = {status: len(report.with_status(status)) for status in JobStatus}
        table = Table.grid(padding=(0, 2))
        table.add_row(f"[green]{t('app.summary_downloaded')}", str(counts[JobStatus.COMPLETED]))
        table.add_row(f"[cyan]{t('app.summary_present')}", str(counts[JobStatus.SKIPPED]))
        if counts[JobStatus.CANCELLED]:
            table.add_row(f"[yellow]{t('app.summary_cancelled')}", str(counts[JobStatus.CANCELLED]))
        failed = counts[JobStatus.FAILED] + len(probe_failures)
        table.add_row(f"[red]{t('app.summary_failed')}" if failed else t("app.summary_failed"), str(failed))
        self._console.print()
        self._console.print(table)
        self._console.print(t("app.saved_to", path=escape(display_path(output_dir))))
        if report.failures_of_kind(ErrorKind.AUTH_REQUIRED):
            self._console.print(f"[dim]{t('app.auth_hint')}")

    def _print_equivalent_command(self, mode: Mode, urls: Sequence[str], plan: DownloadPlan) -> None:
        """Teach the flags: the one-line command that repeats this run without questions."""
        self._console.print(f"\n[dim]{t('app.next_time')}")
        self._console.print(f"  {escape(equivalent_command(mode, urls, plan, self._auth))}", soft_wrap=True)
        if len(urls) > MAX_LISTED_URLS:
            self._console.print(f"[dim]  {t('app.replace_urls')}")
