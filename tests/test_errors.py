import pytest

from ytgrab.errors import ErrorKind, VideoError, classify_error, clean_message


@pytest.mark.parametrize(
    ("message", "kind"),
    [
        (
            "ERROR: [youtube] abc: Join this channel to get access to members-only content",
            ErrorKind.AUTH_REQUIRED,
        ),
        ("This video is available to this channel's members on level: Tier 1", ErrorKind.AUTH_REQUIRED),
        ("Private video. Sign in if you've been granted access to this video", ErrorKind.AUTH_REQUIRED),
        (
            "Sign in to confirm your age. This video may be inappropriate for some users.",
            ErrorKind.AUTH_REQUIRED,
        ),
        ("Sign in to confirm you're not a bot. Use --cookies-from-browser", ErrorKind.AUTH_REQUIRED),
        ("Premieres in 3 hours", ErrorKind.NOT_YET_AVAILABLE),
        ("This live event will begin in a few moments.", ErrorKind.NOT_YET_AVAILABLE),
        ("The uploader has not made this video available in your country", ErrorKind.GEO_BLOCKED),
        ("This video is not available in your country", ErrorKind.GEO_BLOCKED),
        ("Video unavailable. This video has been removed by the uploader", ErrorKind.UNAVAILABLE),
        ("This video is unavailable", ErrorKind.UNAVAILABLE),
        ("This video is no longer available because the account has been terminated", ErrorKind.UNAVAILABLE),
        ("HTTP Error 429: Too Many Requests", ErrorKind.RATE_LIMITED),
        ("Unable to download webpage: <urlopen error timed out>", ErrorKind.NETWORK),
        ("HTTP Error 503: Service Unavailable", ErrorKind.NETWORK),
        ("Connection reset by peer", ErrorKind.NETWORK),
        ("[Errno 28] No space left on device", ErrorKind.DISK),
        ("Permission denied: '/root/x.mp4'", ErrorKind.DISK),
        ("Something completely different", ErrorKind.UNKNOWN),
        ("ERROR: [youtube] abcsslefghi: Something odd", ErrorKind.UNKNOWN),  # id must not match "ssl"
        ("[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred", ErrorKind.NETWORK),
        ("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed", ErrorKind.UNKNOWN),
        ("<urlopen error [Errno 8] nodename nor servname provided, or not known>", ErrorKind.NETWORK),
        ("Unable to download API page: HTTP Error 400", ErrorKind.NETWORK),
        ("unable to download video data: [Errno 36] File name too long", ErrorKind.DISK),
        ("[WinError 5] Access is denied: 'C:\\x.mp4'", ErrorKind.DISK),
        (
            "[WinError 32] The process cannot access the file because it is being used by another process",
            ErrorKind.DISK,
        ),
        ("The playlist does not exist.", ErrorKind.UNAVAILABLE),
    ],
)
def test_classify_error(message, kind):
    assert classify_error(message) is kind


def test_transient_kinds():
    assert ErrorKind.NETWORK.is_transient
    assert ErrorKind.RATE_LIMITED.is_transient
    assert not ErrorKind.AUTH_REQUIRED.is_transient
    assert not ErrorKind.UNAVAILABLE.is_transient


def test_clean_message_strips_prefix_and_colors():
    raw = "\x1b[0;31mERROR:\x1b[0m [youtube] dQw4w9WgXcQ: Video unavailable\nmore details"
    assert clean_message(raw) == "Video unavailable"
    assert clean_message("") == "unknown error"


def test_video_error_classifies_and_cleans():
    error = VideoError("ERROR: [youtube] dQw4w9WgXcQ: Private video. Sign in if you've been granted access")
    assert error.kind is ErrorKind.AUTH_REQUIRED
    assert str(error).startswith("Private video")
    assert VideoError("x", ErrorKind.DISK).kind is ErrorKind.DISK


def test_control_characters_are_removed_from_remote_messages():
    message = VideoError("ERROR: [youtube] abcdefghijk: bad\x1b]52;c;ZXZpbA==\x1b\\ \x9b2J title\x07").args[0]
    assert "\x1b" not in message and "\x9b" not in message and "\x07" not in message
