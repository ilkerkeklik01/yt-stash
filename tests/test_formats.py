import pytest

from ytgrab.errors import UsageError
from ytgrab.formats import (
    collect_quality_options,
    default_height,
    parse_quality,
    resolutions_from_formats,
    resolve_quality,
    short_side,
)
from ytgrab.models import QualityOption, Resolution, VideoInfo, VideoQuality

from conftest import AUDIO_FORMAT, fmt


def make_video(*heights: int) -> VideoInfo:
    return VideoInfo(id="x", title="x", url="u", resolutions=tuple(Resolution(h, 30) for h in heights))


def test_short_side_handles_vertical_and_missing_width():
    assert short_side({"width": 1920, "height": 1080}) == 1080
    assert short_side({"width": 1080, "height": 1920}) == 1080  # Shorts
    assert short_side({"height": 720}) == 720
    assert short_side({"height": None}) is None
    assert short_side({"height": 0, "width": 100}) is None


def test_resolutions_ignore_audio_and_storyboards_and_sort_descending():
    formats = [
        AUDIO_FORMAT,
        {"format_id": "sb0", "ext": "mhtml", "vcodec": "none", "height": 90, "width": 160},
        fmt(360),
        fmt(2160, fps=60),
        fmt(1080),
    ]
    assert [r.height for r in resolutions_from_formats(formats)] == [2160, 1080, 360]


def test_resolutions_merge_same_height_keeping_max_fps_and_hdr():
    formats = [fmt(1080, fps=30), fmt(1080, fps=59.94, hdr=True), fmt(1080, fps=None)]
    assert resolutions_from_formats(formats) == (Resolution(1080, 60, True),)


def test_resolution_labels():
    assert Resolution(1080, 30).label == "1080p"
    assert Resolution(1080, 60).label == "1080p60"
    assert Resolution(2160, 60, hdr=True).label == "2160p60 HDR"
    assert Resolution(144).label == "144p"


def test_collect_quality_options_counts_videos_per_height():
    options = collect_quality_options([make_video(1080, 720), make_video(720, 360), make_video(720)])
    assert [(o.height, o.video_count) for o in options] == [(1080, 1), (720, 3), (360, 1)]


@pytest.mark.parametrize(
    ("heights", "expected"),
    [
        ([2160, 1080, 720], 1080),  # 1080p available -> 1080p
        ([720, 480, 144], 720),  # no 1080p -> maximum
        ([2160, 1440], 2160),  # only higher ones -> maximum
        ([], None),
    ],
)
def test_default_height(heights, expected):
    options = [QualityOption(h, video_count=1) for h in heights]
    assert default_height(options) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1080", 1080),
        ("720p", 720),
        (" 4320P ", 4320),
        ("144", 144),
        ("best", "best"),
        ("MAX", "best"),
        ("worst", "worst"),
        ("lowest", "worst"),
    ],
)
def test_parse_quality(value, expected):
    assert parse_quality(value) == expected


@pytest.mark.parametrize("value", ["", "hd", "1080i", "0", "-720", "7", "12345"])
def test_parse_quality_rejects_garbage(value):
    with pytest.raises(UsageError):
        parse_quality(value)


def test_resolve_quality():
    options = [QualityOption(h, video_count=1) for h in (1440, 720, 144)]
    assert resolve_quality("best", options) == VideoQuality(1440)
    assert resolve_quality("worst", options) == VideoQuality(144)
    assert resolve_quality(1080, options) == VideoQuality(1080)
    assert resolve_quality("best", []) == VideoQuality(None)
