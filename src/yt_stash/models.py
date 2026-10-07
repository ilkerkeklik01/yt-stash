"""Plain data types shared across the application."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path


class Mode(Enum):
    """What kind of URL(s) the user wants to download."""

    VIDEO = "video"
    PLAYLIST = "playlist"


@dataclass(frozen=True)
class Resolution:
    """One video resolution offered for a single video.

    ``height`` is the *short side* of the frame, i.e. the number YouTube shows as
    "1080p" — also for vertical videos such as Shorts (1080x1920 is "1080p").
    """

    height: int
    fps: int | None = None
    hdr: bool = False

    def merged_with(self, other: Resolution) -> Resolution:
        """Same height, keeping the highest frame rate and HDR if either has it.

        Returns an instance of ``type(self)``, so subclasses keep their extra fields.
        """
        fps = max(self.fps or 0, other.fps or 0) or None
        return replace(self, fps=fps, hdr=self.hdr or other.hdr)

    @property
    def label(self) -> str:
        fps = f"{self.fps}" if self.fps and self.fps > 30 else ""
        hdr = " HDR" if self.hdr else ""
        return f"{self.height}p{fps}{hdr}"


@dataclass(frozen=True)
class QualityOption(Resolution):
    """A resolution offered across a batch of videos, with how many videos have it."""

    video_count: int = 0


@dataclass(frozen=True)
class VideoInfo:
    """Metadata of a probed video that is ready to be downloaded."""

    id: str
    title: str
    url: str
    resolutions: tuple[Resolution, ...] = ()
    duration: int | None = None
    channel: str | None = None
    playlist_index: int | None = None

    @property
    def max_height(self) -> int | None:
        return max((r.height for r in self.resolutions), default=None)


@dataclass(frozen=True)
class ProbeTarget:
    """A URL waiting to be probed, with optional context from a playlist."""

    url: str
    title: str | None = None
    playlist_index: int | None = None


@dataclass(frozen=True)
class PlaylistInfo:
    id: str
    title: str
    entries: tuple[ProbeTarget, ...]


@dataclass(frozen=True)
class SubtitleOptions:
    """Which subtitles to download. Empty ``languages`` disables subtitles."""

    languages: tuple[str, ...] = ()
    include_auto_generated: bool = False
    embed: bool = False

    @property
    def enabled(self) -> bool:
        return bool(self.languages)


@dataclass(frozen=True)
class VideoQuality:
    """Download video+audio at ``height`` (closest lower resolution if missing).

    ``height=None`` means "best available".
    """

    height: int | None


@dataclass(frozen=True)
class AudioOnly:
    """Download audio only and convert it to ``codec`` (m4a, mp3 or opus)."""

    codec: str = "m4a"


Selection = VideoQuality | AudioOnly


@dataclass(frozen=True)
class DownloadPlan:
    """The choices of one run that the user can still change on the review screen.

    ``output_dir`` is the folder the user chose; playlists get a subfolder inside it.
    """

    selection: Selection
    output_dir: Path
    container: str
    subtitles: SubtitleOptions
    overwrite: bool
    jobs: int


class Stage(str, Enum):
    """What a download is currently doing."""

    VIDEO = "video"  # video-only stream
    AUDIO = "audio"  # audio-only stream
    FILE = "file"  # single file containing video and audio
    PROCESSING = "processing"  # merging / converting with ffmpeg


@dataclass(frozen=True)
class ProgressEvent:
    """Progress of one video download, translated from yt-dlp hooks."""

    video_id: str
    stage: Stage
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    speed: float | None = None
    eta: int | None = None
