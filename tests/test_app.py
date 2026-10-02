"""End-to-end workflow tests of :class:`ytgrab.app.App` with fake I/O."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from rich.console import Console

from ytgrab.app import App, RunOptions
from ytgrab.auth import AuthConfig, BrowserSpec
from ytgrab.environment import Environment
from ytgrab.errors import AuthConfigError, OutputDirectoryError, UsageError, VideoError
from ytgrab.gateway import LoadedCookies
from ytgrab.models import AudioOnly, Mode, VideoQuality
from ytgrab.prompts import NonInteractivePrompter
from ytgrab.retry import RetryPolicy

from conftest import FakeClient, ScriptedPrompter, url_of, vid, video_info

FULL_ENV = Environment(ffmpeg_available=True, js_runtimes={"deno": {"path": "deno"}})
MEMBERS_ONLY = "Join this channel to get access to members-only content"
FIREFOX = AuthConfig(browser=BrowserSpec("firefox"))


class Harness:
    """Builds an App wired to fakes and exposes what happened."""

    def __init__(
        self,
        tmp_path: Path,
        client: FakeClient,
        prompter=None,
        *,
        interactive=True,
        env=FULL_ENV,
        authed_client: FakeClient | None = None,
        cookie_error: bool = False,
    ):
        self.output = io.StringIO()
        self.console = Console(file=self.output, width=200, force_terminal=False)
        self.prompter = prompter or ScriptedPrompter(directory=tmp_path)
        self.client = client
        self.authed_client = authed_client
        self.cookie_error = cookie_error
        self.cookie_loads: list[AuthConfig] = []
        self.interactive = interactive
        self.env = env

    def client_factory(self, cookies: LoadedCookies | None):
        if cookies is not None and self.authed_client is not None:
            return self.authed_client
        return self.client

    def cookie_loader(self, auth: AuthConfig) -> LoadedCookies:
        self.cookie_loads.append(auth)
        if self.cookie_error:
            raise AuthConfigError("could not find firefox cookies database")
        return LoadedCookies("cookie-text", youtube_cookie_count=5)

    def run(self, **options) -> int:
        app = App(
            RunOptions(**options),
            prompter=self.prompter,
            console=self.console,
            environment=self.env,
            client_factory=self.client_factory,
            cookie_loader=self.cookie_loader,
            interactive=self.interactive,
            retry=RetryPolicy(attempts=2, base_delay=0),
        )
        return app.run()

    @property
    def text(self) -> str:
        return self.output.getvalue()


def videos_client(*ids: str, heights=(1080, 720, 360)) -> FakeClient:
    return FakeClient(videos={url_of(i): video_info(i, heights=heights) for i in ids})


def downloaded_ids(client: FakeClient) -> list[str]:
    return sorted(url[-11:] for url, _ in client.downloads)


def test_video_mode_defaults_to_1080p_and_asks_quality_directory_confirm(tmp_path):
    client = videos_client(vid(1), vid(2))
    harness = Harness(tmp_path, client)

    code = harness.run(mode=Mode.VIDEO, urls=(vid(1), f"https://youtu.be/{vid(2)}"))

    assert code == 0
    assert harness.prompter.asked == ["quality", "directory", "confirm"]
    assert downloaded_ids(client) == [vid(1), vid(2)]
    params = client.downloads[0][1]
    assert params["format_sort"][0] == "res:1080"
    assert params["paths"]["home"] == str(tmp_path)


def test_default_is_max_quality_when_1080p_missing(tmp_path):
    client = videos_client(vid(1), heights=(720, 480))
    harness = Harness(tmp_path, client)
    assert harness.run(mode=Mode.VIDEO, urls=(vid(1),)) == 0
    assert client.downloads[0][1]["format_sort"][0] == "res:720"


def test_quality_options_are_union_of_all_videos(tmp_path):
    client = FakeClient(
        videos={
            url_of(vid(1)): video_info(vid(1), heights=(2160, 1080)),
            url_of(vid(2)): video_info(vid(2), heights=(720, 144)),
        }
    )
    harness = Harness(tmp_path, client, ScriptedPrompter(directory=tmp_path, quality=VideoQuality(144)))
    harness.run(mode=Mode.VIDEO, urls=(vid(1), vid(2)))
    assert [o.height for o in harness.prompter.quality_options] == [2160, 1080, 720, 144]
    assert all(params["format_sort"][0] == "res:144" for _, params in client.downloads)


def test_flags_skip_questions(tmp_path):
    client = videos_client(vid(1))
    harness = Harness(tmp_path, client)
    harness.run(mode=Mode.VIDEO, urls=(vid(1),), quality="worst", output_dir=tmp_path / "out")
    assert harness.prompter.asked == ["confirm"]
    assert client.downloads[0][1]["format_sort"][0] == "res:360"
    assert (tmp_path / "out").is_dir()


def test_audio_only_flag(tmp_path):
    client = videos_client(vid(1))
    harness = Harness(tmp_path, client)
    harness.run(mode=Mode.VIDEO, urls=(vid(1),), audio_codec="mp3", output_dir=tmp_path)
    assert client.downloads[0][1]["postprocessors"][0]["preferredcodec"] == "mp3"


def test_prompted_audio_selection(tmp_path):
    client = videos_client(vid(1))
    harness = Harness(tmp_path, client, ScriptedPrompter(directory=tmp_path, quality=AudioOnly("opus")))
    harness.run(mode=Mode.VIDEO, urls=(vid(1),))
    assert client.downloads[0][1]["postprocessors"][0]["preferredcodec"] == "opus"


def test_declining_confirmation_downloads_nothing(tmp_path):
    client = videos_client(vid(1))
    harness = Harness(tmp_path, client, ScriptedPrompter(directory=tmp_path, confirm_answer=False))
    assert harness.run(mode=Mode.VIDEO, urls=(vid(1),)) == 0
    assert client.downloads == []


def test_wizard_mode_asks_mode_and_urls(tmp_path):
    client = videos_client(vid(1))
    prompter = ScriptedPrompter(mode=Mode.VIDEO, urls=[vid(1)], directory=tmp_path)
    harness = Harness(tmp_path, client, prompter)
    assert harness.run() == 0
    assert prompter.asked[:2] == ["mode", "urls"]


def test_playlist_mode_creates_folder_and_numbers_files(tmp_path):
    entries = [{"id": vid(i), "title": f"T{i}"} for i in range(1, 4)]
    client = videos_client(vid(1), vid(2), vid(3))
    client.playlist = {"id": "PLx", "title": "Best: of/2024", "entries": entries}
    harness = Harness(tmp_path, client)

    code = harness.run(mode=Mode.PLAYLIST, urls=("https://www.youtube.com/playlist?list=PLx",))

    assert code == 0
    folder = tmp_path / "Best_ of_2024"
    assert folder.is_dir()
    templates = sorted(params["outtmpl"]["default"] for _, params in client.downloads)
    assert templates[0].startswith("01 - ") and templates[2].startswith("03 - ")
    assert all(params["paths"]["home"] == str(folder) for _, params in client.downloads)


def test_playlist_mode_requires_exactly_one_url(tmp_path):
    harness = Harness(tmp_path, FakeClient())
    with pytest.raises(UsageError):
        harness.run(
            mode=Mode.PLAYLIST,
            urls=("https://www.youtube.com/playlist?list=A", "https://www.youtube.com/playlist?list=B"),
        )


def test_empty_playlist_is_not_an_error(tmp_path):
    client = FakeClient(playlist={"id": "PLx", "title": "Empty", "entries": []})
    harness = Harness(tmp_path, client)
    assert harness.run(mode=Mode.PLAYLIST, urls=("https://www.youtube.com/playlist?list=PLx",)) == 0
    assert "Nothing to download" in harness.text


def test_unavailable_videos_are_reported_and_others_downloaded(tmp_path):
    client = videos_client(vid(1))  # vid(2) is unknown -> "Video unavailable"
    harness = Harness(tmp_path, client)
    code = harness.run(mode=Mode.VIDEO, urls=(vid(1), vid(2)))
    assert code == 1
    assert downloaded_ids(client) == [vid(1)]
    assert "Video unavailable" in harness.text


def test_all_videos_unavailable(tmp_path):
    harness = Harness(tmp_path, FakeClient())
    assert harness.run(mode=Mode.VIDEO, urls=(vid(1),)) == 1
    assert harness.prompter.asked == []


def test_members_only_video_prompts_for_auth_and_retries(tmp_path):
    public = videos_client(vid(1))
    public.videos[url_of(vid(2))] = VideoError(MEMBERS_ONLY)
    authed = videos_client(vid(1), vid(2))
    prompter = ScriptedPrompter(directory=tmp_path, auth_answers=[FIREFOX])
    harness = Harness(tmp_path, public, prompter, authed_client=authed)

    code = harness.run(mode=Mode.VIDEO, urls=(vid(1), vid(2)))

    assert code == 0
    assert prompter.asked[0] == "auth"
    assert harness.cookie_loads == [FIREFOX]
    assert downloaded_ids(authed) == [vid(1), vid(2)]


def test_auth_prompt_can_be_skipped(tmp_path):
    client = videos_client(vid(1))
    client.videos[url_of(vid(2))] = VideoError(MEMBERS_ONLY)
    prompter = ScriptedPrompter(directory=tmp_path, auth_answers=[None])
    harness = Harness(tmp_path, client, prompter)
    assert harness.run(mode=Mode.VIDEO, urls=(vid(1), vid(2))) == 1
    assert downloaded_ids(client) == [vid(1)]
    assert "--cookies-from-browser" in harness.text


def test_invalid_auth_is_asked_again(tmp_path):
    client = videos_client()
    client.videos[url_of(vid(1))] = VideoError(MEMBERS_ONLY)
    prompter = ScriptedPrompter(directory=tmp_path, auth_answers=[FIREFOX, None])
    harness = Harness(tmp_path, client, prompter, cookie_error=True)
    assert harness.run(mode=Mode.VIDEO, urls=(vid(1),)) == 1
    assert prompter.asked.count("auth") == 2
    assert "cookies database" in harness.text


def test_non_interactive_never_prompts_for_auth(tmp_path):
    client = videos_client()
    client.videos[url_of(vid(1))] = VideoError(MEMBERS_ONLY)
    harness = Harness(tmp_path, client, NonInteractivePrompter(), interactive=False)
    assert harness.run(mode=Mode.VIDEO, urls=(vid(1),), output_dir=tmp_path) == 1


def test_configured_auth_loads_cookies_upfront(tmp_path):
    authed = videos_client(vid(1))
    harness = Harness(tmp_path, FakeClient(), authed_client=authed)
    assert harness.run(mode=Mode.VIDEO, urls=(vid(1),), auth=FIREFOX) == 0
    assert harness.cookie_loads == [FIREFOX]
    assert downloaded_ids(authed) == [vid(1)]


def test_configured_auth_failure_is_fatal(tmp_path):
    harness = Harness(tmp_path, FakeClient(), cookie_error=True)
    with pytest.raises(AuthConfigError):
        harness.run(mode=Mode.VIDEO, urls=(vid(1),), auth=FIREFOX)


def test_private_playlist_prompts_for_auth(tmp_path):
    public = FakeClient(playlist=VideoError("This playlist is private. Sign in to confirm"))
    authed = videos_client(vid(1))
    authed.playlist = {"id": "PLx", "title": "Mine", "entries": [{"id": vid(1)}]}
    prompter = ScriptedPrompter(directory=tmp_path, auth_answers=[FIREFOX])
    harness = Harness(tmp_path, public, prompter, authed_client=authed)
    assert harness.run(mode=Mode.PLAYLIST, urls=("https://www.youtube.com/playlist?list=PLx",)) == 0
    assert downloaded_ids(authed) == [vid(1)]


def test_download_auth_failure_triggers_auth_and_retry(tmp_path):
    def needs_login(url, attempt):
        raise VideoError(MEMBERS_ONLY)

    public = videos_client(vid(1))
    public.download_behaviour = needs_login
    authed = videos_client(vid(1))
    prompter = ScriptedPrompter(directory=tmp_path, auth_answers=[FIREFOX])
    harness = Harness(tmp_path, public, prompter, authed_client=authed)
    assert harness.run(mode=Mode.VIDEO, urls=(vid(1),)) == 0
    assert downloaded_ids(authed) == [vid(1)]


def test_failed_download_gives_exit_code_1(tmp_path):
    def broken(url, attempt):
        raise VideoError("Something completely different")

    client = videos_client(vid(1))
    client.download_behaviour = broken
    harness = Harness(tmp_path, client)
    assert harness.run(mode=Mode.VIDEO, urls=(vid(1),)) == 1


def test_list_qualities_does_not_download(tmp_path):
    client = videos_client(vid(1), heights=(2160, 1080))
    harness = Harness(tmp_path, client)
    assert harness.run(mode=Mode.VIDEO, urls=(vid(1),), list_qualities=True) == 0
    assert client.downloads == []
    assert "2160p" in harness.text and "1080p (default)" in harness.text


def test_invalid_directory_is_asked_again_interactively(tmp_path):
    blocker = tmp_path / "file"
    blocker.touch()

    class TwoDirectories(ScriptedPrompter):
        answers = [blocker, tmp_path / "good"]

        def ask_directory(self, default):
            self.asked.append("directory")
            return self.answers.pop(0)

    client = videos_client(vid(1))
    harness = Harness(tmp_path, client, TwoDirectories())
    assert harness.run(mode=Mode.VIDEO, urls=(vid(1),)) == 0
    assert harness.prompter.asked.count("directory") == 2
    assert client.downloads[0][1]["paths"]["home"] == str(tmp_path / "good")


def test_invalid_output_flag_is_fatal(tmp_path):
    blocker = tmp_path / "file"
    blocker.touch()
    harness = Harness(tmp_path, videos_client(vid(1)))
    with pytest.raises(OutputDirectoryError):
        harness.run(mode=Mode.VIDEO, urls=(vid(1),), output_dir=blocker)


def test_environment_warnings(tmp_path):
    harness = Harness(tmp_path, videos_client(vid(1)), env=Environment(ffmpeg_available=False))
    harness.run(mode=Mode.VIDEO, urls=(vid(1),))
    assert "ffmpeg was not found" in harness.text
    assert "No JavaScript runtime" in harness.text
    assert harness.client.downloads[0][1]["format"] == "b"


def test_quality_flag_not_offered_warns(tmp_path):
    harness = Harness(tmp_path, videos_client(vid(1), heights=(720,)))
    harness.run(mode=Mode.VIDEO, urls=(vid(1),), quality=1080)
    assert "1080p is not offered" in harness.text


def test_interrupted_download_exits_130(tmp_path):
    def interrupted(url, attempt):
        raise KeyboardInterrupt

    client = videos_client(vid(1))
    client.download_behaviour = interrupted
    harness = Harness(tmp_path, client)
    assert harness.run(mode=Mode.VIDEO, urls=(vid(1),)) == 130
    assert "Interrupted" in harness.text
    assert "auth" not in harness.prompter.asked


def test_unavailable_playlist_offers_sign_in_when_signed_out(tmp_path):
    public = FakeClient(playlist=VideoError("The playlist does not exist."))
    authed = videos_client(vid(1))
    authed.playlist = {"id": "PLx", "title": "Private", "entries": [{"id": vid(1)}]}
    prompter = ScriptedPrompter(directory=tmp_path, auth_answers=[FIREFOX])
    harness = Harness(tmp_path, public, prompter, authed_client=authed)
    assert harness.run(mode=Mode.PLAYLIST, urls=("https://www.youtube.com/playlist?list=PLx",)) == 0
    assert prompter.asked[0] == "auth"


def test_unavailable_playlist_with_auth_configured_is_fatal(tmp_path):
    client = FakeClient(playlist=VideoError("The playlist does not exist."))
    harness = Harness(tmp_path, client, authed_client=client)
    with pytest.raises(VideoError):
        harness.run(mode=Mode.PLAYLIST, urls=("https://www.youtube.com/playlist?list=PLx",), auth=FIREFOX)
    assert "auth" not in harness.prompter.asked


def test_input_order_is_kept_after_sign_in(tmp_path):
    public = videos_client(vid(1), vid(3))
    public.videos[url_of(vid(2))] = VideoError(MEMBERS_ONLY)
    authed = videos_client(vid(1), vid(2), vid(3))
    authed.download_behaviour = lambda url, attempt: Path(url[-11:])
    prompter = ScriptedPrompter(directory=tmp_path, auth_answers=[FIREFOX])
    harness = Harness(tmp_path, public, prompter, authed_client=authed)

    harness.run(mode=Mode.VIDEO, urls=(vid(1), vid(2), vid(3)), jobs=1)

    assert [url[-11:] for url, _ in authed.downloads] == [vid(1), vid(2), vid(3)]


def test_already_present_videos_are_reported(tmp_path):
    client = videos_client(vid(1))
    client.download_behaviour = lambda url, attempt: None
    harness = Harness(tmp_path, client)
    assert harness.run(mode=Mode.VIDEO, urls=(vid(1),)) == 0
    assert "already downloaded" in harness.text
