import _thread
import threading
import time
from pathlib import Path

import pytest

from ytgrab.concurrency import map_interruptible
from ytgrab.downloader import DownloadJob, DownloadManager, JobStatus
from ytgrab.errors import DownloadCancelledError, ErrorKind, VideoError
from ytgrab.models import VideoInfo
from ytgrab.retry import RetryPolicy

from conftest import FakeClient, url_of, vid

NO_WAIT = RetryPolicy(attempts=3, base_delay=0.0)


def job(n: int, tmp_path: Path) -> DownloadJob:
    video = VideoInfo(id=vid(n), title=f"Video {n}", url=url_of(vid(n)))
    return DownloadJob(video, {"paths": {"home": str(tmp_path)}})


class RecordingReporter:
    def __init__(self):
        self.events = []

    def job_started(self, video):
        self.events.append(("start", video.id))

    def job_progress(self, video, event):
        self.events.append(("progress", video.id))

    def job_retrying(self, video, attempt, delay, error):
        self.events.append(("retry", video.id, attempt))

    def job_finished(self, result):
        self.events.append(("finish", result.video.id, result.status))


def test_all_jobs_complete_in_input_order(tmp_path):
    client = FakeClient()
    reporter = RecordingReporter()
    report = DownloadManager(client, workers=3, reporter=reporter).run([job(i, tmp_path) for i in range(5)])

    assert [r.status for r in report.results] == [JobStatus.COMPLETED] * 5
    assert [r.video.id for r in report.results] == [vid(i) for i in range(5)]
    assert report.results[0].path == tmp_path / f"{vid(0)}.mp4"
    assert not report.interrupted
    assert sum(1 for e in reporter.events if e[0] == "finish") == 5


def test_skipped_when_client_returns_none(tmp_path):
    client = FakeClient(download_behaviour=lambda url, attempt: None)
    report = DownloadManager(client).run([job(1, tmp_path)])
    assert report.results[0].status is JobStatus.SKIPPED


def test_transient_errors_are_retried_then_succeed(tmp_path):
    def flaky(url, attempt):
        if attempt < 3:
            raise VideoError("HTTP Error 429: Too Many Requests")
        return Path("ok.mp4")

    client = FakeClient(download_behaviour=flaky)
    reporter = RecordingReporter()
    report = DownloadManager(client, retry=NO_WAIT, reporter=reporter).run([job(1, tmp_path)])

    result = report.results[0]
    assert result.status is JobStatus.COMPLETED
    assert client.attempts[url_of(vid(1))] == 3
    assert [e for e in reporter.events if e[0] == "retry"] == [("retry", vid(1), 1), ("retry", vid(1), 2)]


def test_transient_errors_give_up_after_max_attempts(tmp_path):
    def always_down(url, attempt):
        raise VideoError("Connection reset by peer")

    client = FakeClient(download_behaviour=always_down)
    report = DownloadManager(client, retry=NO_WAIT).run([job(1, tmp_path)])
    assert report.results[0].status is JobStatus.FAILED
    assert client.attempts[url_of(vid(1))] == 3
    assert report.results[0].error.kind is ErrorKind.NETWORK


def test_permanent_errors_are_not_retried(tmp_path):
    def members_only(url, attempt):
        raise VideoError("Join this channel to get access to members-only content")

    client = FakeClient(download_behaviour=members_only)
    report = DownloadManager(client, retry=NO_WAIT).run([job(1, tmp_path)])
    assert report.results[0].status is JobStatus.FAILED
    assert client.attempts[url_of(vid(1))] == 1


def test_unexpected_exception_fails_only_that_job(tmp_path):
    def buggy(url, attempt):
        if url.endswith(vid(1)):
            raise KeyError("oops")
        return Path("ok.mp4")

    report = DownloadManager(FakeClient(download_behaviour=buggy)).run([job(1, tmp_path), job(2, tmp_path)])
    assert [r.status for r in report.results] == [JobStatus.FAILED, JobStatus.COMPLETED]
    assert report.results[0].error.kind is ErrorKind.UNKNOWN


def test_cancelled_download(tmp_path):
    def cancelled(url, attempt):
        raise DownloadCancelledError("cancelled")

    report = DownloadManager(FakeClient(download_behaviour=cancelled)).run([job(1, tmp_path)])
    assert report.results[0].status is JobStatus.CANCELLED


def test_cancel_before_start_skips_all_jobs(tmp_path):
    manager = DownloadManager(FakeClient())
    manager.cancel()
    report = manager.run([job(1, tmp_path), job(2, tmp_path)])
    assert [r.status for r in report.results] == [JobStatus.CANCELLED] * 2


def test_downloads_run_in_parallel(tmp_path):
    barrier = threading.Barrier(3, timeout=5)

    def wait_for_peers(url, attempt):
        barrier.wait()  # deadlocks (and times out) unless 3 downloads run at the same time
        return Path("ok.mp4")

    client = FakeClient(download_behaviour=wait_for_peers)
    report = DownloadManager(client, workers=3).run([job(i, tmp_path) for i in range(3)])
    assert all(r.status is JobStatus.COMPLETED for r in report.results)


def test_worker_count_is_respected(tmp_path):
    active, peak, lock = 0, 0, threading.Lock()

    def track(url, attempt):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return Path("ok.mp4")

    DownloadManager(FakeClient(download_behaviour=track), workers=2).run([job(i, tmp_path) for i in range(6)])
    assert peak == 2


def test_retry_policy_delays():
    policy = RetryPolicy(attempts=5, base_delay=2, max_delay=30, rate_limit_factor=4)
    assert [policy.delay(a, ErrorKind.NETWORK) for a in (1, 2, 3, 4, 5)] == [2, 4, 8, 16, 30]
    assert policy.delay(1, ErrorKind.RATE_LIMITED) == 8


def test_map_interruptible_preserves_order_and_propagates_errors():
    assert map_interruptible(lambda x: x * 2, [3, 1, 2], workers=3) == [6, 2, 4]
    assert map_interruptible(lambda x: x, [], workers=3) == []

    interrupted = []

    def fail(x):
        raise ValueError(x)

    with pytest.raises(ValueError):
        map_interruptible(fail, [1], workers=1, on_abort=lambda: interrupted.append(True))
    assert interrupted == [True]


def test_interrupt_marks_unfinished_and_failed_jobs_cancelled(tmp_path):
    def interrupted(url, attempt):
        if url.endswith(vid(1)):
            raise KeyboardInterrupt  # what the main thread sees after Ctrl+C
        raise VideoError("ffmpeg exited with code 255")  # killed by the same Ctrl+C

    client = FakeClient(download_behaviour=interrupted)
    report = DownloadManager(client, workers=1).run([job(1, tmp_path), job(2, tmp_path)])
    assert report.interrupted
    assert [r.status for r in report.results] == [JobStatus.CANCELLED, JobStatus.CANCELLED]


def test_retry_is_abandoned_when_cancelled_during_backoff(tmp_path):
    manager = DownloadManager(FakeClient(), retry=RetryPolicy(attempts=3, base_delay=30))

    def network_error_then_cancel(url, attempt):
        manager.cancel()
        raise VideoError("Connection reset by peer")

    manager._client = FakeClient(download_behaviour=network_error_then_cancel)
    started = time.monotonic()
    report = manager.run([job(1, tmp_path)])
    assert report.results[0].status is JobStatus.CANCELLED
    assert time.monotonic() - started < 5  # did not sit out the 30 s back-off


def test_ctrl_c_aborts_promptly_without_waiting():
    release = threading.Event()
    aborted = []

    def slow_or_interrupting(x):
        if x == 0:
            _thread.interrupt_main()  # exactly what Ctrl+C does to the main thread
            return x
        release.wait(5)
        return x

    started = time.monotonic()
    with pytest.raises(KeyboardInterrupt):
        map_interruptible(
            slow_or_interrupting, [0, 1], workers=2, on_abort=lambda: aborted.append(1), wait_on_abort=False
        )
    assert time.monotonic() - started < 2
    assert aborted == [1]
    release.set()
