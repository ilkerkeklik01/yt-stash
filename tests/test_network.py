"""Real end-to-end tests against YouTube. Excluded by default; run with ``pytest -m network``."""

import pytest

from yt_stash.cli import main

ME_AT_THE_ZOO = "https://www.youtube.com/watch?v=jNQXAC9IVRw"  # 19 s, the first YouTube video

pytestmark = pytest.mark.network


def test_download_lowest_quality_and_skip_on_second_run(tmp_path, capsys):
    assert main(["video", ME_AT_THE_ZOO, "-q", "worst", "-o", str(tmp_path), "--yes"]) == 0
    files = list(tmp_path.glob("*.mp4"))
    assert len(files) == 1 and files[0].stat().st_size > 0

    assert main(["video", ME_AT_THE_ZOO, "-q", "worst", "-o", str(tmp_path), "--yes"]) == 0
    assert "already downloaded" in capsys.readouterr().out


def test_list_qualities(capsys):
    assert main(["video", ME_AT_THE_ZOO, "--list-qualities", "--yes"]) == 0
    assert "144p" in capsys.readouterr().out
