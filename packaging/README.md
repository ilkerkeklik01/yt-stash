# Packaging recipes

Reference recipes for installing yt-stash with native package managers (tracking issue
[#13](https://github.com/ilkerkeklik01/yt-stash/issues/13)). They are **not** part of the Python
package. Each recipe belongs in its own repository (a Homebrew tap, a Scoop bucket, the AUR), which
is where users install it from; these copies are the starting point and are updated at each release.

| System | Recipe | Publish to | Status |
|---|---|---|---|
| Homebrew | [`homebrew/yt-stash.rb`](homebrew/yt-stash.rb) | tap `ilkerkeklik01/homebrew-tap`, folder `Formula/` | needs `resource` blocks, untested |
| Scoop | [`scoop/yt-stash.json`](scoop/yt-stash.json) | bucket repository, folder `bucket/` | untested (needs Windows) |
| AUR | [`aur/PKGBUILD`](aur/PKGBUILD) | `ssh://aur@aur.archlinux.org/yt-stash.git` | untested (needs Arch) |

All three install from the PyPI release, so a version must be on PyPI first. Checksums of the sdist
and wheel are on <https://pypi.org/project/yt-stash/#files>.

## Homebrew

1. Create the repository `ilkerkeklik01/homebrew-tap` and copy the formula to `Formula/yt-stash.rb`.
2. Generate the Python dependency blocks (Homebrew ignores files uploaded in the last 24 hours, so
   wait a day after a release):

   ```bash
   brew tap ilkerkeklik01/tap
   brew update-python-resources ilkerkeklik01/tap/yt-stash
   ```

3. Test: `brew install --build-from-source ilkerkeklik01/tap/yt-stash && brew test yt-stash && brew audit --strict --online ilkerkeklik01/tap/yt-stash`.

## Scoop

Copy `yt-stash.json` into a bucket repository (`bucket/yt-stash.json`) and test with
`scoop install .\bucket\yt-stash.json` on Windows. The `checkver`/`autoupdate` entries let Scoop's
excavator workflow follow new PyPI releases by itself.

## AUR

The AUR depends on `yt-dlp` (which provides the Python module) rather than `python-yt-dlp`. Check
that `yt-dlp-ejs` and other `yt-dlp[default]` extras are installed on a clean Arch container, then
`makepkg --printsrcinfo > .SRCINFO`, `namcap PKGBUILD`, build with `makepkg -si`, and push `PKGBUILD`
and `.SRCINFO`.

## At each release

Bump the version, URLs and checksums in all three recipes (Scoop and Homebrew can do it
automatically as described above; the AUR needs `pkgver` and `sha256sums`, or `updpkgsums`).
