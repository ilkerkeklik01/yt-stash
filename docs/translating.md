# Adding or improving a translation

yt-stash speaks English and Turkish. Every piece of text a user sees goes through the catalog in
`src/yt_stash/i18n/`, so adding a language needs no changes to the program logic.

## Improve an existing translation

Edit the message in `src/yt_stash/i18n/tr.py` (or the catalog of your language) and open a pull request.
Keep the placeholders (`{count}`, `{path}`, …) and the markup tags (`[b]`, `[dim]`, `[/]`) exactly as in
the English message; the tests check this.

## Add a language

1. Copy `src/yt_stash/i18n/en.py` to `src/yt_stash/i18n/<code>.py`, where `<code>` is the two-letter
   [ISO 639-1](https://en.wikipedia.org/wiki/List_of_ISO_639_language_codes) code (for example `de`).
2. Translate every value. Keep **all keys, placeholders and markup identical** to `en.py`.
3. Register the language in `src/yt_stash/i18n/__init__.py`:

   ```python
   from yt_stash.i18n import de, en, tr

   LANGUAGES = {"en": "English", "tr": "Türkçe", "de": "Deutsch"}  # a language's own name
   CATALOGS = {"en": en.MESSAGES, "tr": tr.MESSAGES, "de": de.MESSAGES}
   ```

4. If your language has a distinctive Windows display-language id, add it to `_windows_ui_language`.
5. Run `pytest tests/test_i18n.py`. It fails if a key, placeholder or markup tag differs from English.
6. Run `ruff check . && ruff format .`. Letters such as `ı` or `ß` can trigger the ambiguous-character
   rules RUF001/RUF002; add your catalog to the per-file ignores in `pyproject.toml` like `tr.py`.
7. Add a line to the [CHANGELOG](../CHANGELOG.md) under *Unreleased → Added* and open a pull request.

## Rules for writing messages

- **Whole sentences.** Write complete templates and never build a sentence from translated fragments;
  word order and suffixes differ between languages.
- **Plurals.** Use the pairs `key.one` and `key.other` (`tn()` picks one by count). Languages with more
  plural forms are welcome to discuss the design in an issue first.
- **What stays English** in every language: command-line flags, quality keywords (`best`, `worst`),
  commands in examples, messages produced by yt-dlp, and the `argparse` words `usage:` and `options:`.
- Text is looked up when it is shown (`t("key")`), never stored in module-level constants, so changing
  the language from the main menu applies immediately.
