class YtStash < Formula
  include Language::Python::Virtualenv

  desc "Download YouTube videos and playlists from the terminal"
  homepage "https://github.com/ilkerkeklik01/yt-stash"
  url "https://files.pythonhosted.org/packages/e0/fd/b7b5afe18faef801989231087613cf3608e84a672c51905035f4d7501491/yt_stash-1.0.1.tar.gz"
  sha256 "fa4e49b695e89a9b84bd4da3b7d3116a575ccdc23b3d70402665460b7f9db8a3"
  license "MIT"

  depends_on "deno"
  depends_on "ffmpeg"
  depends_on "python@3.14"

  # Add the `resource` blocks for the Python dependencies with:
  #   brew update-python-resources yt-stash
  # (see packaging/README.md)

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/yt-stash --version")
  end
end
