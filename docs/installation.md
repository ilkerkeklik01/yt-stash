# Installation

yt-stash needs **Python 3.10 or newer**. Two extra tools unlock full quality, and both are optional but
strongly recommended:

| Tool | What it does for you | Without it |
|---|---|---|
| **ffmpeg** | Merges the separate video and audio streams YouTube uses above 360p, converts audio (mp3), embeds subtitles | Quality is limited and mp3/embedding fail |
| **deno** (or node / bun) | A JavaScript runtime that YouTube's player requires to reveal most formats | Often only low qualities are offered |

yt-stash shows a warning when one is missing, and **Check setup** in the main menu tells you what is
found and how to install the rest.

Pick your system: [macOS](#macos) · [Windows](#windows) · [Linux](#linux) · [From source](#from-source) ·
[Update or uninstall](#update-and-uninstall)

---

## macOS

1. Install [Homebrew](https://brew.sh) if you don't have it.
2. Install the tools:

   ```bash
   brew install python pipx ffmpeg deno
   pipx ensurepath
   ```

3. Open a **new** terminal window, then install yt-stash:

   ```bash
   pipx install yt-stash
   ```

4. Check it works:

   ```bash
   yt-stash --version
   yt-stash
   ```

> Downloading with Safari cookies needs *Full Disk Access* for your terminal; see
> [Authentication](authentication.md#platform-notes).

## Windows

Use **PowerShell** or **Windows Terminal** (not an old `cmd` window, which renders the menus poorly).

1. Install the tools with [winget](https://learn.microsoft.com/windows/package-manager/winget/), which
   comes with Windows 10 and 11:

   ```powershell
   winget install Python.Python.3.13
   winget install Gyan.FFmpeg
   winget install DenoLand.Deno
   ```

2. **Close and reopen** PowerShell so the new programs are on your `PATH`.
3. Install pipx and yt-stash:

   ```powershell
   py -m pip install --user pipx
   py -m pipx ensurepath
   ```

   Close and reopen PowerShell once more, then:

   ```powershell
   pipx install yt-stash
   ```

4. Check it works:

   ```powershell
   yt-stash --version
   yt-stash
   ```

> If `yt-stash` is "not recognized", the pipx folder is not on your `PATH` yet. Run
> `py -m pipx ensurepath` and open a new terminal.

## Linux

Install Python, pipx and ffmpeg with your package manager, then deno with its installer.

<details open>
<summary><b>Debian, Ubuntu, Linux Mint</b></summary>

```bash
sudo apt update
sudo apt install python3 pipx ffmpeg
pipx ensurepath
curl -fsSL https://deno.land/install.sh | sh
```

</details>

<details>
<summary><b>Fedora</b></summary>

```bash
sudo dnf install python3 pipx ffmpeg-free
pipx ensurepath
curl -fsSL https://deno.land/install.sh | sh
```

`ffmpeg-free` is limited in codecs; for full support enable [RPM Fusion](https://rpmfusion.org) and
install `ffmpeg` instead.

</details>

<details>
<summary><b>Arch Linux, Manjaro</b></summary>

```bash
sudo pacman -S python python-pipx ffmpeg deno
pipx ensurepath
```

</details>

<details>
<summary><b>openSUSE</b></summary>

```bash
sudo zypper install python3 python3-pipx ffmpeg
pipx ensurepath
curl -fsSL https://deno.land/install.sh | sh
```

</details>

Open a **new** terminal (so `~/.local/bin` is on your `PATH`), then:

```bash
pipx install yt-stash
yt-stash --version
```

Your distribution's repositories may carry an older Python than 3.10. In that case install a newer one
(for example with [uv](https://docs.astral.sh/uv/): `uv tool install yt-stash` fetches a suitable Python
by itself).

## With uv

[uv](https://docs.astral.sh/uv/) is a fast alternative to pipx and works the same on every system:

```bash
uv tool install yt-stash
```

## With pip

Use pip inside a virtual environment if you don't want pipx:

```bash
python -m venv ~/.venvs/yt-stash
source ~/.venvs/yt-stash/bin/activate        # Windows: .venvs\yt-stash\Scripts\activate
pip install yt-stash
```

Avoid `pip install` into the system Python: recent Linux distributions refuse it (PEP 668), and pipx
exists to solve exactly that.

## From source

To try an unreleased change or to contribute:

```bash
git clone https://github.com/ilkerkeklik01/yt-stash.git
cd yt-stash
python -m venv .venv
source .venv/bin/activate                    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

or install straight from GitHub without cloning:

```bash
pipx install git+https://github.com/ilkerkeklik01/yt-stash.git
```

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the development workflow.

## Update and uninstall

YouTube changes often and yt-stash relies on [yt-dlp](https://github.com/yt-dlp/yt-dlp) to follow it.
**If downloads suddenly start failing, update first.**

| | pipx | uv | pip |
|---|---|---|---|
| Update yt-stash and yt-dlp | `pipx upgrade yt-stash` | `uv tool upgrade yt-stash` | `pip install -U yt-stash` |
| Uninstall | `pipx uninstall yt-stash` | `uv tool uninstall yt-stash` | `pip uninstall yt-stash` |

yt-stash keeps one small file, `config.json`, holding the language you picked in the menu. Delete it
after uninstalling if you want no trace:

| System | Location |
|---|---|
| macOS | `~/Library/Application Support/yt-stash/` |
| Linux | `~/.config/yt-stash/` (or `$XDG_CONFIG_HOME/yt-stash/`) |
| Windows | `%APPDATA%\yt-stash\` |

## Troubleshooting the installation

| Symptom | Fix |
|---|---|
| `yt-stash: command not found` / "not recognized" | Run `pipx ensurepath`, then open a **new** terminal. |
| `error: externally-managed-environment` | Use pipx or uv instead of plain `pip`. |
| `requires a different Python` | Install Python 3.10 or newer (see your system's section above). |
| Menus look garbled on Windows | Use Windows Terminal or PowerShell, not the legacy console. |
| Only low qualities offered | Install ffmpeg **and** deno, then run **Check setup** in the menu. |
