from pathlib import Path

from ytgrab.models import AudioOnly, SubtitleOptions, VideoInfo, VideoQuality
from ytgrab.options import (
    OUTPUT_TEMPLATE,
    DownloadSettings,
    build_download_params,
    format_params,
    output_template,
    subtitle_params,
)

VIDEO = VideoInfo(id="abcdefghijk", title="t", url="u")


def test_video_quality_uses_resolution_sort_and_merge_fallback():
    params = format_params(VideoQuality(1080), "mp4", ffmpeg_available=True)
    assert params["format"] == "bv*+ba/b"
    assert params["format_sort"][:2] == ["res:1080", "fps"]
    assert "vcodec:h264" in params["format_sort"]
    assert params["merge_output_format"] == "mp4/mkv"


def test_best_quality_has_no_resolution_cap():
    params = format_params(VideoQuality(None), "mkv", ffmpeg_available=True)
    assert params["format_sort"] == []
    assert params["merge_output_format"] == "mkv"


def test_without_ffmpeg_only_single_file_formats_are_used():
    params = format_params(VideoQuality(720), "mp4", ffmpeg_available=False)
    assert params["format"] == "b"
    assert "merge_output_format" not in params


def test_audio_only_converts_with_ffmpeg():
    params = format_params(AudioOnly("mp3"), "mp4", ffmpeg_available=True)
    assert params["format"] == "ba/b"
    assert params["postprocessors"][0]["key"] == "FFmpegExtractAudio"
    assert params["postprocessors"][0]["preferredcodec"] == "mp3"


def test_audio_only_without_ffmpeg_downloads_native_audio():
    params = format_params(AudioOnly("mp3"), "mp4", ffmpeg_available=False)
    assert params == {"format": "ba[ext=m4a]/ba/b"}


def test_subtitle_params():
    assert subtitle_params(SubtitleOptions(), embed_possible=True) == {}
    params = subtitle_params(SubtitleOptions(("en", "tr"), True, True), embed_possible=True)
    assert params["subtitleslangs"] == ["en", "tr"]
    assert params["writeautomaticsub"] is True
    assert params["postprocessors"][0]["key"] == "FFmpegEmbedSubtitle"
    assert "postprocessors" not in subtitle_params(SubtitleOptions(("en",), embed=True), embed_possible=False)


def test_all_subtitles_exclude_live_chat():
    params = subtitle_params(SubtitleOptions(("all",)), embed_possible=False)
    assert params["subtitleslangs"] == ["all", "-live_chat"]


def test_output_template_prefixes_playlist_index():
    assert output_template(VIDEO) == OUTPUT_TEMPLATE
    indexed = VideoInfo(id="a", title="t", url="u", playlist_index=7)
    assert output_template(indexed, playlist_size=150) == f"007 - {OUTPUT_TEMPLATE}"
    assert output_template(indexed, playlist_size=9) == f"07 - {OUTPUT_TEMPLATE}"


def test_build_download_params_combines_everything(tmp_path: Path):
    settings = DownloadSettings(
        output_dir=tmp_path,
        selection=VideoQuality(720),
        subtitles=SubtitleOptions(("en",), embed=True),
    )
    params = build_download_params(settings, VIDEO, ffmpeg_available=True)
    assert params["paths"] == {"home": str(tmp_path)}
    assert params["overwrites"] is None  # keep finished files, resume partial ones
    assert params["noplaylist"] is True
    assert params["windowsfilenames"] is True
    assert params["format_sort"][0] == "res:720"
    assert [pp["key"] for pp in params["postprocessors"]] == ["FFmpegEmbedSubtitle"]


def test_build_download_params_audio_never_embeds_subtitles(tmp_path: Path):
    settings = DownloadSettings(
        output_dir=tmp_path,
        selection=AudioOnly("m4a"),
        subtitles=SubtitleOptions(("en",), embed=True),
        overwrite=True,
    )
    params = build_download_params(settings, VIDEO, ffmpeg_available=True)
    assert [pp["key"] for pp in params["postprocessors"]] == ["FFmpegExtractAudio"]
    assert params["overwrites"] is True
    assert params["final_ext"] == "m4a"
