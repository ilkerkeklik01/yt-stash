"""Quality detection and selection logic (pure functions, no I/O).

Selection rule: the user picks one resolution for the whole batch. Every video is then
downloaded at that resolution, or the closest *lower* one it offers, or — if it only
offers higher ones — its lowest. yt-dlp implements exactly this with the
``res:<height>`` format-sort key, so a single choice never fails for a missing resolution.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from typing import Any, Literal

from ytgrab.errors import UsageError
from ytgrab.i18n import t
from ytgrab.models import QualityOption, Resolution, VideoInfo, VideoQuality

DEFAULT_HEIGHT = 1080
AUDIO_CODECS = ("m4a", "mp3", "opus")

QualitySpec = int | Literal["best", "worst"]


def short_side(fmt: Mapping[str, Any]) -> int | None:
    """Return the "p" value of a format: the shorter frame side, or the height."""
    width, height = fmt.get("width"), fmt.get("height")
    if isinstance(height, int) and height > 0:
        if isinstance(width, int) and width > 0:
            return min(width, height)
        return height
    return None


def _is_video_format(fmt: Mapping[str, Any]) -> bool:
    # Storyboards (mhtml) and audio-only streams have vcodec "none".
    return fmt.get("vcodec") != "none" and fmt.get("ext") != "mhtml"


def resolutions_from_formats(formats: Iterable[Mapping[str, Any]]) -> tuple[Resolution, ...]:
    """Collapse yt-dlp format dicts into distinct resolutions, highest first.

    For each height the highest frame rate wins and HDR is flagged if any format has it.
    """
    best: dict[int, Resolution] = {}
    for fmt in formats:
        if not _is_video_format(fmt):
            continue
        height = short_side(fmt)
        if height is None:
            continue
        fps_value = fmt.get("fps")
        fps = round(fps_value) if isinstance(fps_value, (int, float)) and fps_value > 0 else None
        resolution = Resolution(height, fps, fmt.get("dynamic_range") not in (None, "SDR"))
        current = best.get(height)
        best[height] = resolution if current is None else current.merged_with(resolution)
    return tuple(sorted(best.values(), key=lambda r: r.height, reverse=True))


def collect_quality_options(videos: Sequence[VideoInfo]) -> list[QualityOption]:
    """Union of all resolutions across ``videos``, highest first, with availability counts."""
    merged: dict[int, QualityOption] = {}
    for video in videos:
        for res in video.resolutions:
            current = merged.get(res.height)
            if current is None:
                merged[res.height] = QualityOption(res.height, res.fps, res.hdr, video_count=1)
            else:
                merged[res.height] = replace(current.merged_with(res), video_count=current.video_count + 1)
    return sorted(merged.values(), key=lambda o: o.height, reverse=True)


def default_height(options: Sequence[QualityOption]) -> int | None:
    """1080p if any video offers it, otherwise the highest resolution available."""
    heights = [o.height for o in options]
    if DEFAULT_HEIGHT in heights:
        return DEFAULT_HEIGHT
    return max(heights, default=None)


def parse_quality(value: str) -> QualitySpec:
    """Parse a ``--quality`` flag value such as ``1080``, ``720p``, ``best`` or ``worst``."""
    text = value.strip().lower()
    if text in ("best", "max", "highest"):
        return "best"
    if text in ("worst", "min", "lowest"):
        return "worst"
    match = re.fullmatch(r"(\d{2,4})p?", text)
    if match and int(match.group(1)) > 0:
        return int(match.group(1))
    raise UsageError(t("formats.invalid_quality", value=value))


def resolve_quality(spec: QualitySpec, options: Sequence[QualityOption]) -> VideoQuality:
    """Turn a parsed ``--quality`` value into a concrete selection for this batch."""
    heights = [o.height for o in options]
    if spec == "best":
        return VideoQuality(max(heights, default=None))
    if spec == "worst":
        return VideoQuality(min(heights, default=None))
    return VideoQuality(spec)
