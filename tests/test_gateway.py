"""Tests of the yt-dlp gateway with yt-dlp's YoutubeDL replaced by a stub."""

from __future__ import annotations

import io
import threading
from pathlib import Path

import pytest
from yt_dlp.utils import DownloadCancelled, DownloadError

from ytgrab import gateway
from ytgrab.auth import AuthConfig
from ytgrab.environment import Environment
from ytgrab.errors import AuthConfigError, DownloadCancelledError, ErrorKind, VideoError
from ytgrab.gateway import YtDlpClient, load_auth_cookies
from ytgrab.models import Stage

ENV = Environment(
    ffmpeg_available=True,
    ffmpeg_location=Path("/opt/ffmpeg"),
    js_runtimes={"node": {"path": "/usr/bin/node"}},
)


class StubYDL:
    """Stands in for yt_dlp.YoutubeDL; behaviour is set per test via class attributes."""

    instances: list[StubYDL] = []
    result: dict | None = None
    error: Exception | None = None
    hook_events: list[dict] = []

    def __init__(self, params):
        self.params = params
        StubYDL.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=True, process=True):
        self.call = {"url": url, "download": download, "process": process}
        for event in StubYDL.hook_events:
            for hook in self.params.get("progress_hooks", []):
                hook(event)
        if StubYDL.error is not None:
            raise StubYDL.error
        return StubYDL.result


@pytest.fixture(autouse=True)
def stub_ydl(monkeypatch):
    StubYDL.instances, StubYDL.result, StubYDL.error, StubYDL.hook_events = [], None, None, []
    monkeypatch.setattr(gateway.yt_dlp, "YoutubeDL", StubYDL)
    return StubYDL


def test_base_params_include_environment_and_cookie_copy():
    client = YtDlpClient(ENV, gateway.LoadedCookies("# cookies\n", 1))
    StubYDL.result = {"id": "x"}
    client.extract_video("u")
    params = StubYDL.instances[0].params
    assert params["js_runtimes"] == {"node": {"path": "/usr/bin/node"}}
    assert params["ffmpeg_location"] == str(Path("/opt/ffmpeg"))
    assert isinstance(params["cookiefile"], io.StringIO)
    assert params["cookiefile"].getvalue() == "# cookies\n"
    assert StubYDL.instances[0].call == {"url": "u", "download": False, "process": False}


def test_extractor_instance_is_reused_per_thread():
    client = YtDlpClient(ENV)
    StubYDL.result = {"id": "x"}
    client.extract_video("a")
    client.extract_video("b")
    thread = threading.Thread(target=client.extract_video, args=("c",))
    thread.start()
    thread.join()
    assert len(StubYDL.instances) == 2


def test_extract_errors_are_wrapped():
    StubYDL.error = DownloadError("ERROR: [youtube] abcdefghijk: Join this channel to get access")
    with pytest.raises(VideoError) as excinfo:
        YtDlpClient(ENV).extract_video("u")
    assert excinfo.value.kind is ErrorKind.AUTH_REQUIRED


def test_extract_playlist_is_flat():
    StubYDL.result = {"id": "PL", "entries": []}
    assert YtDlpClient(ENV).extract_playlist("u") == {"id": "PL", "entries": []}
    assert StubYDL.instances[0].params["extract_flat"] == "in_playlist"


def test_empty_extraction_result_is_an_error():
    with pytest.raises(VideoError):
        YtDlpClient(ENV).extract_playlist("u")
    with pytest.raises(VideoError):
        YtDlpClient(ENV).extract_video("u")


def test_download_reports_progress_and_returns_final_path():
    StubYDL.hook_events = [
        {
            "status": "downloading",
            "downloaded_bytes": 10,
            "total_bytes": 100,
            "speed": 5.0,
            "eta": 18,
            "info_dict": {"id": "abc", "vcodec": "avc1", "acodec": "none"},
        },
        {"status": "error", "info_dict": {}},
    ]
    StubYDL.result = {"requested_downloads": [{"filepath": "/tmp/a.mp4"}]}
    events = []

    outcome = YtDlpClient(ENV).download(
        "u", {"format": "b"}, on_progress=events.append, cancel_event=threading.Event()
    )

    assert outcome.path == Path("/tmp/a.mp4")
    assert not outcome.already_present
    assert len(events) == 1
    assert (events[0].stage, events[0].downloaded_bytes, events[0].total_bytes) == (Stage.VIDEO, 10, 100)
    assert StubYDL.instances[0].params["format"] == "b"
    assert StubYDL.instances[0].call["download"] is True


def test_download_without_transfer_means_already_present():
    StubYDL.result = {"requested_downloads": [{"filepath": "/tmp/a.mp4"}]}
    outcome = YtDlpClient(ENV).download("u", {}, on_progress=print, cancel_event=threading.Event())
    assert outcome.already_present
    assert outcome.path == Path("/tmp/a.mp4")


def test_download_cancellation_via_hook():
    cancel = threading.Event()
    cancel.set()
    StubYDL.hook_events = [{"status": "downloading", "info_dict": {}}]
    with pytest.raises(DownloadCancelledError):
        YtDlpClient(ENV).download("u", {}, on_progress=print, cancel_event=cancel)
    assert StubYDL.instances == []  # cancelled before even starting


def test_download_cancelled_exception_is_translated():
    StubYDL.error = DownloadCancelled()
    with pytest.raises(DownloadCancelledError):
        YtDlpClient(ENV).download("u", {}, on_progress=print, cancel_event=threading.Event())


def test_download_os_error_is_wrapped():
    StubYDL.error = OSError(28, "No space left on device")
    with pytest.raises(VideoError) as excinfo:
        YtDlpClient(ENV).download("u", {}, on_progress=print, cancel_event=threading.Event())
    assert excinfo.value.kind is ErrorKind.DISK


def test_final_path_fallbacks():
    assert gateway._final_path({"filepath": "/x.mkv"}) == Path("/x.mkv")
    assert gateway._final_path({}) is None


def test_load_auth_cookies_from_file(tmp_path, monkeypatch):
    monkeypatch.undo()  # use the real yt-dlp: no network involved
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text(
        "# Netscape HTTP Cookie File\n"
        ".youtube.com\tTRUE\t/\tTRUE\t2147483647\tSID\tsecret\n"
        ".example.com\tTRUE\t/\tFALSE\t2147483647\tother\tvalue\n",
        encoding="utf-8",
    )
    original = cookie_file.read_text(encoding="utf-8")

    cookies = load_auth_cookies(AuthConfig(cookies_file=cookie_file))

    assert cookies.youtube_cookie_count == 1
    assert "SID\tsecret" in cookies.text
    assert cookie_file.read_text(encoding="utf-8") == original  # never rewritten


def test_load_auth_cookies_invalid_file(tmp_path, monkeypatch):
    monkeypatch.undo()
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("this is not a cookie file\twith\ttabs\n", encoding="utf-8")
    with pytest.raises(AuthConfigError):
        load_auth_cookies(AuthConfig(cookies_file=cookie_file))
