import pytest

from ytgrab.errors import UsageError
from ytgrab.urls import (
    extract_playlist_id,
    extract_video_id,
    normalize_playlist_url,
    normalize_video_urls,
)

VIDEO_ID = "dQw4w9WgXcQ"
CANONICAL = f"https://www.youtube.com/watch?v={VIDEO_ID}"


@pytest.mark.parametrize(
    "raw",
    [
        f"https://www.youtube.com/watch?v={VIDEO_ID}",
        f"https://youtube.com/watch?v={VIDEO_ID}&t=42s",
        f"http://m.youtube.com/watch?feature=share&v={VIDEO_ID}",
        f"https://music.youtube.com/watch?v={VIDEO_ID}&list=RDAMVM",
        f"https://youtu.be/{VIDEO_ID}?si=abc",
        f"https://www.youtube.com/shorts/{VIDEO_ID}",
        f"https://www.youtube.com/live/{VIDEO_ID}?feature=share",
        f"https://www.youtube.com/embed/{VIDEO_ID}",
        f"https://www.youtube-nocookie.com/embed/{VIDEO_ID}",
        f"www.youtube.com/watch?v={VIDEO_ID}",
        f"youtu.be/{VIDEO_ID}",
        f"  {VIDEO_ID}  ",
        f"https://WWW.YOUTUBE.COM/watch?v={VIDEO_ID}",
    ],
)
def test_extract_video_id_accepts_all_common_forms(raw):
    assert extract_video_id(raw) == VIDEO_ID


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not a url",
        "https://vimeo.com/123456",
        "https://www.youtube.com/watch?v=short",
        "https://www.youtube.com/playlist?list=PL123",
        "https://www.youtube.com/@somechannel",
        f"https://evil.com/watch?v={VIDEO_ID}",
        f"https://youtube.com.evil.com/watch?v={VIDEO_ID}",
        f"https://www.youtube.com/watch?v={VIDEO_ID}%0A",
    ],
)
def test_extract_video_id_rejects_non_videos(raw):
    assert extract_video_id(raw) is None


def test_normalize_video_urls_deduplicates_and_keeps_order():
    other = "abcdefghijk"
    urls = normalize_video_urls(
        [f"https://youtu.be/{VIDEO_ID}", other, f"https://www.youtube.com/shorts/{VIDEO_ID}", ""]
    )
    assert urls == [CANONICAL, f"https://www.youtube.com/watch?v={other}"]


def test_normalize_video_urls_lists_all_invalid_inputs():
    with pytest.raises(UsageError) as excinfo:
        normalize_video_urls(["bad-one", VIDEO_ID, "bad-two"])
    assert "bad-one" in str(excinfo.value)
    assert "bad-two" in str(excinfo.value)


def test_normalize_video_urls_hints_playlist_mode():
    with pytest.raises(UsageError, match="ytgrab playlist"):
        normalize_video_urls(["https://www.youtube.com/playlist?list=PLabcdef"])


def test_normalize_video_urls_requires_at_least_one_url():
    with pytest.raises(UsageError):
        normalize_video_urls(["", "  "])


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://www.youtube.com/playlist?list=PLabc_DEF-123", "PLabc_DEF-123"),
        (f"https://www.youtube.com/watch?v={VIDEO_ID}&list=PLxyz", "PLxyz"),
        ("youtube.com/playlist?list=UUMOabc", "UUMOabc"),
        ("https://music.youtube.com/playlist?list=OLAK5uy_abc", "OLAK5uy_abc"),
        ("https://www.youtube.com/playlist", None),
        ("https://example.com/playlist?list=PLabc", None),
    ],
)
def test_extract_playlist_id(raw, expected):
    assert extract_playlist_id(raw) == expected


def test_normalize_playlist_url_is_canonical():
    url = normalize_playlist_url(f"https://www.youtube.com/watch?v={VIDEO_ID}&list=PLxyz&index=3")
    assert url == "https://www.youtube.com/playlist?list=PLxyz"


def test_normalize_playlist_url_hints_video_mode():
    with pytest.raises(UsageError, match="ytgrab video"):
        normalize_playlist_url(f"https://youtu.be/{VIDEO_ID}")
