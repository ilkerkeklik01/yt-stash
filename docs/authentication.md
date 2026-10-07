# Members-only, private and age-restricted videos

YouTube doesn't allow password logins from third-party tools, so yt-stash uses the cookies
of a browser where you are **signed in to YouTube** (with an active membership for
members-only content):

```bash
yt-stash video URL --cookies-from-browser firefox
yt-stash video URL --cookies-from-browser "chrome:Profile 1"      # a specific profile
yt-stash playlist URL --cookies-from-browser edge
yt-stash video URL --cookies ~/cookies.txt                         # exported cookies file
yt-stash video URL --paste-cookies                                 # paste them, used once
```

Supported browsers: brave, chrome, chromium, edge, firefox, opera, safari, vivaldi, whale.
Full syntax: `BROWSER[+KEYRING][:PROFILE][::CONTAINER]` (same as yt-dlp).

If you don't pass any of these and a video turns out to need sign-in, yt-stash **asks you**
(interactive mode) for a browser, a cookies file or pasted cookies, and retries just those videos.

## Paste cookies (used once, never saved)

Nothing is stored on disk:

1. In your browser, open youtube.com (signed in), then the developer tools (F12) →
   **Network** tab, reload, click any request to `www.youtube.com`, and under *Request
   Headers* copy the value of **cookie**. (The Console's `document.cookie` misses the
   sign-in cookies, which are HttpOnly.) The content of a `cookies.txt` file works too.
2. Choose *Sign-in → Paste cookies* in the menu (or pass `--paste-cookies`) and paste.
   The input is not shown on screen; only its length is.
3. The cookies stay in memory for that one download run and are discarded when it ends,
   whatever the outcome; the next download asks again. Clear your clipboard afterwards.

For scripts, pipe them in instead of typing: `pbpaste | yt-stash video URL --paste-cookies --yes`
(`Get-Clipboard |` on Windows, `xclip -o |` on Linux).

## Tip: all members-only videos of a channel

To download all members-only videos of a channel, take the channel id (`UCxxxx…`),
replace the `UC` prefix with `UUMO`, and use it as a playlist:
`yt-stash playlist "https://www.youtube.com/playlist?list=UUMOxxxx…" --cookies-from-browser firefox`.

## Platform notes

- **Firefox** works on every OS and is the most reliable choice.
- **Chrome/Edge on Windows** may refuse cookie access while the browser is running (app-bound
  encryption). Close the browser, use Firefox, or export a `cookies.txt` instead.
- **Safari (macOS)** requires granting your terminal *Full Disk Access*
  (System Settings → Privacy & Security).
- **macOS keychain**: Chromium-based browsers may trigger one keychain prompt; yt-stash reads
  cookies once and shares them with all parallel downloads.
- **Exporting cookies.txt**: use a browser extension that exports Netscape-format cookies
  while you are on youtube.com. Treat this file like a password and never share it.

yt-stash never modifies your browser data or your cookies file.

## Safety

- Cookies act like a password for your Google account's YouTube session. yt-stash never writes pasted
  cookies to disk, never prints them, and never modifies your browser data or your cookies file.
- Never share a `cookies.txt` file or paste cookies into an issue. See [SECURITY.md](../SECURITY.md).

Back to [Using yt-stash](usage.md).
