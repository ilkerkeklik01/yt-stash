import pytest

from yt_stash.errors import ErrorKind, VideoError
from yt_stash.models import ProbeTarget
from yt_stash.probe import Prober, ProbeResult, playlist_from_info, video_from_info
from yt_stash.retry import RetryPolicy

from conftest import FakeClient, url_of, vid, video_info


def test_playlist_from_info_skips_broken_entries_and_numbers_entries():
    info = {
        "id": "PL1",
        "title": "My list",
        "entries": [
            {"id": vid(1), "title": "One"},
            None,
            {"title": "no id"},
            {"id": vid(4), "title": "[Private video]", "playlist_index": 4},
        ],
    }
    playlist = playlist_from_info(info, "url")
    assert playlist.title == "My list"
    assert [(t.url, t.playlist_index) for t in playlist.entries] == [(url_of(vid(1)), 1), (url_of(vid(4)), 4)]


def test_playlist_from_info_handles_empty_and_untitled():
    playlist = playlist_from_info({"id": "PL2", "entries": None}, "url")
    assert playlist.entries == ()
    assert playlist.title == "PL2"


def test_video_from_info_maps_fields():
    target = ProbeTarget(url_of(vid(1)), playlist_index=3)
    video = video_from_info(video_info(vid(1), heights=(720, 1080)), target)
    assert video.id == vid(1)
    assert [r.height for r in video.resolutions] == [1080, 720]
    assert video.playlist_index == 3
    assert video.max_height == 1080


@pytest.mark.parametrize(
    ("live_status", "kind"),
    [("is_live", ErrorKind.LIVE_IN_PROGRESS), ("is_upcoming", ErrorKind.NOT_YET_AVAILABLE)],
)
def test_video_from_info_rejects_live_streams(live_status, kind):
    with pytest.raises(VideoError) as excinfo:
        video_from_info(video_info(vid(1), live_status=live_status), ProbeTarget("u"))
    assert excinfo.value.kind is kind


def test_prober_collects_successes_and_failures_in_order():
    client = FakeClient(
        videos={
            url_of(vid(1)): video_info(vid(1)),
            url_of(vid(2)): VideoError("Join this channel to get access to members-only content"),
            url_of(vid(3)): video_info(vid(3)),
            url_of(vid(4)): RuntimeError("boom"),
        }
    )
    done = []
    targets = [ProbeTarget(url_of(vid(i))) for i in range(1, 5)]
    result = Prober(client, workers=4).probe(targets, on_done=done.append)

    assert [v.id for v in result.videos] == [vid(1), vid(3)]
    assert [f.error.kind for f in result.failures] == [ErrorKind.AUTH_REQUIRED, ErrorKind.UNKNOWN]
    assert len(done) == 4
    assert result.failures_of_kind(ErrorKind.AUTH_REQUIRED)[0].target == targets[1]


def test_prober_with_no_targets():
    assert Prober(FakeClient()).probe([]).videos == []


def test_probe_result_merge_keeps_playlist_order():
    client = FakeClient(videos={url_of(vid(i)): video_info(vid(i)) for i in range(1, 4)})
    first = Prober(client).probe([ProbeTarget(url_of(vid(i)), playlist_index=i) for i in (1, 3)])
    second = Prober(client).probe([ProbeTarget(url_of(vid(2)), playlist_index=2)])
    order = [ProbeTarget(url_of(vid(i)), playlist_index=i) for i in (1, 2, 3)]
    merged = first.merge(second, order)
    assert [v.id for v in merged.videos] == [vid(1), vid(2), vid(3)]
    assert isinstance(merged, ProbeResult)


def test_probe_result_merge_keeps_input_order_without_playlist_index():
    client = FakeClient(videos={url_of(vid(i)): video_info(vid(i)) for i in range(1, 4)})
    order = [ProbeTarget(url_of(vid(i))) for i in (1, 2, 3)]
    merged = Prober(client).probe([order[0], order[2]]).merge(Prober(client).probe([order[1]]), order)
    assert [v.id for v in merged.videos] == [vid(1), vid(2), vid(3)]


def test_prober_retries_transient_errors():
    calls = []

    class Flaky(FakeClient):
        def extract_video(self, url):
            calls.append(url)
            if len(calls) == 1:
                raise VideoError("HTTP Error 429: Too Many Requests")
            return video_info(vid(1))

    result = Prober(Flaky(), retry=RetryPolicy(attempts=3, base_delay=0)).probe([ProbeTarget(url_of(vid(1)))])
    assert [v.id for v in result.videos] == [vid(1)]
    assert len(calls) == 2


def test_titles_from_youtube_lose_terminal_control_characters():
    info = {
        "id": "PL1",
        "title": "list\x1b[2J",
        "entries": [{"id": "a" * 11, "title": "x\x1b]8;;evil\x1b\\y"}],
    }
    playlist = playlist_from_info(info, "url")
    assert playlist.title == "list[2J"
    assert "\x1b" not in (playlist.entries[0].title or "")
