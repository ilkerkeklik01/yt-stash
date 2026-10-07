# Security policy

## Supported versions

Security fixes go into the latest release. Please update (`pipx upgrade yt-stash`) before reporting.

| Version | Supported |
|---|---|
| Latest `1.x` release | ✅ |
| Anything older | ❌ |

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Use GitHub's private reporting: open the
[Security tab](https://github.com/ilkerkeklik01/yt-stash/security/advisories/new) of this repository
and choose **Report a vulnerability**. Only the maintainer can see the report.

Include what you found, the steps to reproduce it, the yt-stash version (`yt-stash --version`) and your
operating system. A short proof of concept helps.

What to expect, from a single volunteer maintainer:

- an acknowledgement within **7 days**;
- a first assessment (accepted, needs more information, or not a vulnerability) within **14 days**;
- a fix and a coordinated disclosure through a GitHub security advisory, crediting you if you wish.

## What counts

yt-stash handles sensitive data, so these are in scope:

- **Cookies and sign-in data** leaking to disk, logs, messages or `repr` output. Pasted cookies
  (`--paste-cookies`) must stay in memory for one run only.
- yt-stash modifying or writing back to a user's cookies file or browser data.
- **Terminal escape sequences** or control characters from remote text (video titles, error messages)
  reaching the terminal.
- **Path traversal** or writes outside the chosen target folder through crafted titles or playlist data.
- Command or code injection through URLs, file names or settings.

## Out of scope

- Bugs in [yt-dlp](https://github.com/yt-dlp/yt-dlp) itself: please report them
  [there](https://github.com/yt-dlp/yt-dlp/security).
- Videos that fail to download, YouTube changes, or rate limits: these are ordinary bugs, use the
  issue tracker.
- Attacks that need an already compromised machine or account.

## Handling cookies safely

Cookie files and pasted `Cookie` headers act like passwords. Never attach them to an issue, a pull
request or a discussion; the issue forms ask for `-v` output, which is not meant to contain cookie
values, but read it through before posting.
