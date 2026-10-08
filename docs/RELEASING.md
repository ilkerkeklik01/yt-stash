# Releasing (for maintainers)

yt-stash uses [Semantic Versioning](https://semver.org/). A release is a git tag `vX.Y.Z` on `main`;
the [release workflow](../.github/workflows/release.yml) builds the package, publishes it to PyPI with
trusted publishing, and creates the GitHub Release with the changelog notes.

## One-time setup

1. **PyPI**: sign in at <https://pypi.org>, open *Your account → Publishing*, and add a **pending
   publisher** for a new project with these exact values:

   | Field | Value |
   |---|---|
   | PyPI project name | `yt-stash` |
   | Owner | `ilkerkeklik01` |
   | Repository name | `yt-stash` |
   | Workflow name | `release.yml` |
   | Environment name | `pypi` |

   The name is only reserved once the first release is uploaded.
2. **GitHub**: *Settings → Environments → New environment* named `pypi`. Add yourself as a required
   reviewer if you want a manual approval before every upload.
3. Enable two-factor authentication on PyPI and GitHub.

## Choosing the version

| Change since the last release | Bump | Example |
|---|---|---|
| Bug fixes only | patch | 1.0.0 → 1.0.1 |
| New backwards-compatible features | minor | 1.0.1 → 1.1.0 |
| Anything that can break scripts: renamed or removed flags, changed exit codes or output formats | major | 1.1.0 → 2.0.0 |

## Steps

Work on a branch such as `chore/release-1.1.0` and merge it through a pull request like any change.

1. In `CHANGELOG.md`, rename `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD`, add a new empty
   `## [Unreleased]` above it, and update the links at the bottom:

   ```markdown
   [Unreleased]: https://github.com/ilkerkeklik01/yt-stash/compare/vX.Y.Z...HEAD
   [X.Y.Z]: https://github.com/ilkerkeklik01/yt-stash/compare/vPREVIOUS...vX.Y.Z
   ```

   For the very first release the last line is
   `[1.0.0]: https://github.com/ilkerkeklik01/yt-stash/releases/tag/v1.0.0`.
2. Set `__version__` in `src/yt_stash/__init__.py` to `X.Y.Z`.
3. Open the pull request, wait for CI, and merge it.
4. Tag the merge commit and push the tag:

   ```bash
   git switch main && git pull --ff-only
   git tag -a vX.Y.Z -m "yt-stash X.Y.Z"
   git push origin vX.Y.Z
   ```

5. Watch the *Release* workflow in the Actions tab. When it finishes, check
   <https://pypi.org/project/yt-stash/> and run `pipx install yt-stash` (or `pipx upgrade yt-stash`)
   in a clean environment.
6. Update the recipes in [`packaging/`](../packaging/README.md) and the repositories they are published
   to, once they exist.

The workflow refuses to publish if the tag doesn't match `__version__` or the changelog has no section
for the version.

## If something goes wrong

- **Never reuse a version number.** PyPI doesn't allow replacing a file. Fix forward with a patch
  release.
- A broken release can be *yanked* on PyPI (it stays installable by exact pin but is skipped by
  default). Mark it in the changelog as `## [X.Y.Z] - YYYY-MM-DD [YANKED]`.
- A leaked secret (cookie file, token) is a security incident: revoke it first, then follow
  [SECURITY.md](../SECURITY.md).
