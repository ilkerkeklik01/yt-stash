# Contributing

`main` is protected. Nothing is pushed to it directly: every change goes through a short-lived
feature branch and a pull request.

## Workflow

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
   git switch -c feature/paste-cookies
   ```

3. **Commit in small steps.** Use a short imperative subject ("Add one-time pasted cookies").

4. **Check locally before pushing** (CI runs the same):

   ```bash
   pytest
   ruff check . && ruff format --check .
   ```

5. **Push and open a pull request against `main`.**

   ```bash
   git push -u origin HEAD
   gh pr create --fill
   ```

6. **Wait for CI**, fix anything it reports by pushing more commits to the same branch, then
   merge the pull request on GitHub ("Create a merge commit"). The branch is deleted
   automatically after the merge.

7. **Sync and clean up locally.**

   ```bash
   git switch main && git pull --ff-only
   git branch -d <your-branch>
   ```

Keep one branch to one concern, and keep branches short-lived so they don't drift from `main`.

## What protects `main`

These rules are enforced by GitHub (Settings → Branches), for administrators too:

- Changes must arrive through a pull request; direct pushes are rejected.
- All CI checks must pass: `lint` and `test` on Ubuntu, macOS and Windows with Python 3.10 and 3.13.
- The branch must be up to date with `main` before it merges. If `main` moved, merge it into your
  branch (`git merge origin/main`), push, and let CI run again.
- Review conversations must be resolved. No approving review is required, so a single maintainer can
  merge their own pull request once CI is green.
- Force-pushes to `main` and deleting `main` are blocked.

If the CI job list in `.github/workflows/ci.yml` changes (a new OS, a new Python version, a renamed
job), update the required checks in the branch protection settings as well, otherwise pull
requests wait forever for a check that no longer exists.

## Before you open the pull request

- Add or update tests; no default test may touch the network.
- Keep code compatible with Python 3.10 and Windows.
- Update [README.md](README.md) for user-facing changes and
  [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) when behavior or module responsibilities change.
- New user-visible text needs keys in both `i18n/en.py` and `i18n/tr.py`.

See [CLAUDE.md](CLAUDE.md) for the invariants that span several files.
