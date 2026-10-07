"""Translate user-facing download settings into yt-dlp parameter dictionaries (pure)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from yt_stash.models import AudioOnly, Selection, SubtitleOptions, VideoInfo

CONTAINERS = ("mp4", "mkv", "webm")
DEFAULT_CONTAINER = "mp4"
CONCURRENT_FRAGMENTS = 4  # parallel fragment downloads within one video
# The id keeps names unique when two videos share a title; ".150B" bounds the title
# length in bytes so paths stay below Windows' limits.
OUTPUT_TEMPLATE = "%(title).150B [%(id)s].%(ext)s"

# Stream preferences per container, used as a tie-breaker *after* resolution and frame
# rate: mp4 prefers H.264/AAC (plays everywhere) at equal resolution; above 1080p, where
# YouTube offers only VP9/AV1, resolution still wins.
_CONTAINER_SORT = {"mp4": ["vcodec:h264", "ext:mp4:m4a"], "webm": ["ext:webm:webm"], "mkv": []}
# When codecs cannot go into the preferred container, fall back to mkv instead of failing.
_MERGE_FORMAT = {"mp4": "mp4/mkv", "webm": "webm/mkv", "mkv": "mkv"}


@dataclass(frozen=True)
class DownloadSettings:
    """Everything that determines *how* the videos of one run are downloaded."""

    output_dir: Path
    selection: Selection
    container: str = DEFAULT_CONTAINER
    subtitles: SubtitleOptions = field(default_factory=SubtitleOptions)
    overwrite: bool = False  # re-download even if the final file already exists


def split_languages(text: str) -> tuple[str, ...]:
    """``"en, tr"`` -> ``("en", "tr")``."""
    return tuple(lang.strip() for lang in text.split(",") if lang.strip())


def format_params(selection: Selection, container: str, *, ffmpeg_available: bool) -> dict[str, Any]:
    """yt-dlp params choosing the streams for ``selection``."""
    if isinstance(selection, AudioOnly):
        if not ffmpeg_available:
            # Without ffmpeg no conversion is possible; prefer m4a (most compatible).
            return {"format": "ba[ext=m4a]/ba/b"}
        return {
            "format": "ba/b",
            # Lets yt-dlp recognise an already converted file (e.g. .mp3) and skip it.
            "final_ext": selection.codec,
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": selection.codec, "preferredquality": "0"}
            ],
        }

    sort: list[str] = []
    if selection.height is not None:
        sort += [f"res:{selection.height}", "fps"]
    sort += _CONTAINER_SORT[container]

    if not ffmpeg_available:
        # Separate video/audio streams cannot be merged: use single-file formats only.
        return {"format": "b", "format_sort": sort}
    return {"format": "bv*+ba/b", "format_sort": sort, "merge_output_format": _MERGE_FORMAT[container]}


def subtitle_params(subtitles: SubtitleOptions, *, embed_possible: bool) -> dict[str, Any]:
    """yt-dlp params for downloading (and optionally embedding) subtitles."""
    if not subtitles.enabled:
        return {}
    languages = list(subtitles.languages)
    if "all" in languages:
        languages.append("-live_chat")  # live chat replays are huge and not subtitles
    params: dict[str, Any] = {
        "writesubtitles": True,
        "writeautomaticsub": subtitles.include_auto_generated,
        "subtitleslangs": languages,
    }
    if subtitles.embed and embed_possible:
        params["postprocessors"] = [{"key": "FFmpegEmbedSubtitle", "already_have_subtitle": False}]
    return params


def output_template(video: VideoInfo, playlist_size: int | None = None) -> str:
    """File name template; playlist videos are prefixed with their zero-padded index."""
    if video.playlist_index is None:
        return OUTPUT_TEMPLATE
    width = max(2, len(str(playlist_size or video.playlist_index)))
    return f"{video.playlist_index:0{width}d} - {OUTPUT_TEMPLATE}"


def build_download_params(
    settings: DownloadSettings,
    video: VideoInfo,
    *,
    ffmpeg_available: bool,
    playlist_size: int | None = None,
) -> dict[str, Any]:
    """Complete per-video yt-dlp params (excluding hooks, cookies and logging)."""
    is_audio = isinstance(settings.selection, AudioOnly)
    fmt = format_params(settings.selection, settings.container, ffmpeg_available=ffmpeg_available)
    subs = subtitle_params(settings.subtitles, embed_possible=ffmpeg_available and not is_audio)

    postprocessors = [*fmt.pop("postprocessors", []), *subs.pop("postprocessors", [])]

    return {
        "paths": {"home": str(settings.output_dir)},
        "outtmpl": {"default": output_template(video, playlist_size)},
        "windowsfilenames": True,  # identical, portable names on every OS
        "noplaylist": True,
        "continuedl": True,  # resume .part files from interrupted runs
        "overwrites": settings.overwrite or None,  # None: keep finished files, resume partial ones
        "retries": 10,
        "fragment_retries": 10,
        "concurrent_fragment_downloads": CONCURRENT_FRAGMENTS,
        **fmt,
        **subs,
        "postprocessors": postprocessors,
    }
