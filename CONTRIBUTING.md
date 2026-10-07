# Contributing to yt-stash

Thank you for taking the time to contribute! yt-stash is a small project maintained by a volunteer, and
every bug report, documentation fix, translation and pull request makes it better. This guide explains
how to take part. By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).

## Ways to contribute

You don't need to write code to help:

- **Report a bug** with the [bug report form](https://github.com/ilkerkeklik01/yt-stash/issues/new/choose).
  Include `yt-stash --version`, your operating system, the exact command and the output of `-v`.
  Remove cookies and private links first.
- **Suggest a feature** with the feature request form. Describe the problem you want to solve before the
  solution; it helps to find the best fit.
- **Ask a question or share an idea** in [Discussions](https://github.com/ilkerkeklik01/yt-stash/discussions).
- **Improve the documentation**: typos, unclear steps and missing examples are all welcome fixes.
- **Translate**: see [docs/translating.md](docs/translating.md).
- **Triage**: reproduce reported bugs and add details to them.
- **Write code**: pick an issue labelled
  [`good first issue`](https://github.com/ilkerkeklik01/yt-stash/labels/good%20first%20issue) or
  [`help wanted`](https://github.com/ilkerkeklik01/yt-stash/labels/help%20wanted) and say that you are
  working on it, so nobody duplicates the effort.

For anything bigger than a small fix, **open an issue or discussion first**. It avoids the
disappointment of a large pull request that doesn't fit the project's direction.

## Scope

yt-stash is a workflow and UX layer over yt-dlp. These guide what fits:

- Behavior that yt-dlp already provides is used, not reimplemented. Bugs in extraction or downloading
  itself belong to [yt-dlp](https://github.com/yt-dlp/yt-dlp).
- Features should help most users and work on Linux, macOS and Windows.
- yt-stash does not bypass DRM or paywalls, and it will not store credentials. Sign-in works through
  browser cookies the user already has.
- Fewer options are better than many; a feature that needs a long explanation may belong in a script.

A pull request that doesn't fit will be closed with an explanation and thanks. That's never personal.

## Set up your environment

You need Python 3.10 or newer and git.

```bash
git clone https://github.com/ilkerkeklik01/yt-stash.git
cd yt-stash
python -m venv .venv
source .venv/bin/activate                  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Without an activated virtual environment, call `.venv/bin/pytest`, `.venv/bin/ruff` and
`.venv/bin/yt-stash` directly.

Running `yt-stash` by hand reads and writes your real settings file. When experimenting, point
`HOME` (and `XDG_CONFIG_HOME` / `APPDATA`) at a temporary folder.

## Checks to run

CI runs the same checks on Linux, macOS and Windows with Python 3.10 and 3.13:

```bash
pytest                                     # fast, offline test suite
pytest -m network                          # real YouTube download (needs internet; optional)
pytest --cov --cov-report=term-missing     # coverage, as CI runs it
ruff check . && ruff format --check .      # lint and format (line length 110)
ruff format .                              # apply formatting
```

## Making a change

`main` is protected. Nothing is pushed to it directly: every change goes through a short-lived branch and
a pull request. If you are not a maintainer, **fork** the repository first and open the pull request from
your fork.

1. **Start from an up-to-date `main`.**

   ```bash
   git switch main && git pull --ff-only
   ```

2. **Create a branch** named `<type>/<short-kebab-description>`:

   | Prefix      | Use for                                   |
   |-------------|-------------------------------------------|
   | `feature/`  | New behavior or options                   |
   | `fix/`      | Bug fixes                                 |
   | `docs/`     | Documentation only                        |
   | `chore/`    | Tooling, CI, dependencies, refactoring    |

   ```bash
   git switch -c fix/playlist-numbering
   ```

3. **Commit in small steps.** Write a short, imperative subject line ("Fix playlist numbering"); add a
   body that explains *why* when it isn't obvious.

4. **Check locally** (see above), then push and open a pull request against `main`:

   ```bash
   git push -u origin HEAD
   gh pr create --fill          # or use the GitHub website
   ```

5. **Wait for CI** and fix whatever it reports by pushing more commits to the same branch. Reviews
   are discussions: ask questions, push back politely, and expect the same.

6. **Merging.** A maintainer merges the pull request with a merge commit after CI passes. The branch is
   deleted automatically.

Keep one branch to one concern, and keep branches short-lived so they don't drift from `main`.

### Pull request checklist

- Tests added or updated. **No default test may touch the network**; mark real-network tests with
  `@pytest.mark.network`.
- Code stays compatible with **Python 3.10 and Windows** (no PEP 701 f-string nesting of the same
  quote style; use `os.sep`/`pathlib`).
- [README](README.md) and [docs/](docs/) updated for user-facing changes;
  [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) updated when behavior or module responsibilities change.
- A line in [CHANGELOG.md](CHANGELOG.md) under **Unreleased** (see below).
- New user-visible text has keys in both `i18n/en.py` and `i18n/tr.py`. Don't know Turkish? Add the
  English text to both and say so in the pull request; a maintainer will help.

See [CLAUDE.md](CLAUDE.md) for the invariants that span several files, such as "only `gateway.py`
calls the yt-dlp API", and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design.

## The changelog and versions

yt-stash follows [Semantic Versioning](https://semver.org/) and keeps a
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) file. Add one bullet per user-visible change
under `## [Unreleased]`, in the section that fits:

| Section | Use for | Version bump |
|---|---|---|
| Added | new features, flags, languages | minor |
| Changed | behavior changes of existing features | minor, or **major** if scripts can break |
| Deprecated / Removed | features going away or gone | minor / **major** |
| Fixed | bug fixes | patch |
| Security | vulnerability fixes | patch |

The public interface is the command names, flags, exit codes, environment variables and settings file.
Maintainers cut releases as described in [docs/RELEASING.md](docs/RELEASING.md).

## How decisions get made

yt-stash currently has a single maintainer, who decides what is merged and tries to explain every
decision in the open (in the issue or pull request). Regular contributors who show good judgment will be
invited to become maintainers. Questions and decisions stay in public issues and discussions so that
everyone can follow them.

## What protects `main`

These rules are enforced by GitHub, for administrators too:

- Changes must arrive through a pull request; direct pushes are rejected.
- All CI checks must pass: `lint` and `test` on Ubuntu, macOS and Windows with Python 3.10 and 3.13,
  and the `package` build check.
- The branch must be up to date with `main` before it merges. If `main` moved, merge it into your branch
  (`git merge origin/main`), push, and let CI run again.
- Review conversations must be resolved.
- Force-pushes to `main` and deleting `main` are blocked.

(Maintainers: if the job list in `.github/workflows/ci.yml` changes, update the required checks in the
branch protection settings too, otherwise pull requests wait forever for a missing check.)

## Reporting security problems

Please don't use public issues for vulnerabilities; follow [SECURITY.md](SECURITY.md).

## License

By contributing you agree that your contribution is licensed under the project's [MIT License](LICENSE).
