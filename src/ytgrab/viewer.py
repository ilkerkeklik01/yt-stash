"""A full-screen, scrollable page for longer information (setup check, command-line help).

The page uses the terminal's alternate screen, like ``less``: it opens on Enter, scrolls
with the arrow keys and disappears on Esc or q, leaving the menu where it was.
"""

from __future__ import annotations

import io

from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import ANSI, StyleAndTextTuples
from prompt_toolkit.input import Input
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.output import Output
from prompt_toolkit.styles import Style
from rich.console import Console, RenderableType

from ytgrab.i18n import t

# How long a lone Esc byte waits for the rest of a key sequence such as an arrow key.
# prompt_toolkit's 0.5 s makes Esc feel sluggish; 0.1 s is vim's default.
ESC_TIMEOUT = 0.1

_STYLE = Style.from_dict({"title": "bold", "accent": "fg:ansired bold", "footer": "fg:ansibrightblack"})


def render_lines(content: RenderableType, width: int, color_system: str | None) -> list[str]:
    """``content`` rendered by rich as lines of ANSI text, ``width`` columns wide."""
    buffer = io.StringIO()
    console = Console(
        file=buffer,
        width=width,
        force_terminal=color_system is not None,
        color_system=color_system,  # type: ignore[arg-type]
        highlight=False,
    )
    console.print(content)
    return buffer.getvalue().splitlines()


class Page:
    """The lines of ``content`` at the current terminal width and the visible part of them."""

    def __init__(self, content: RenderableType, color_system: str | None) -> None:
        self._content = content
        self._color_system = color_system
        self._width = 0
        self.lines: list[str] = []
        self.top = 0

    def layout(self, columns: int) -> None:
        """Re-render when the width changed (first call, or the terminal was resized)."""
        width = max(20, columns - 2)  # one column of margin on each side
        if width != self._width:
            self._width = width
            self.lines = render_lines(self._content, width, self._color_system)

    def scroll(self, delta: int, height: int) -> None:
        self.top = max(0, min(self.top + delta, len(self.lines) - height))

    def visible(self, height: int) -> range:
        self.scroll(0, height)  # keep the window inside the page after a resize
        return range(self.top, min(self.top + height, len(self.lines)))


def show_page(
    title: str,
    content: RenderableType,
    *,
    color_system: str | None,
    input: Input | None = None,
    output: Output | None = None,
) -> None:
    """Show ``content`` full screen until the user presses Esc, q, Enter or ←."""
    page = Page(content, color_system)
    app: Application[None]

    def body_height() -> int:
        size = app.output.get_size()
        page.layout(size.columns)
        return max(1, size.rows - 3)  # title, blank line, footer

    def body() -> ANSI:
        height = body_height()
        return ANSI("\n".join(" " + page.lines[i] for i in page.visible(height)))

    def header() -> StyleAndTextTuples:
        return [("class:accent", "▶ "), ("class:title", title)]

    def footer() -> StyleAndTextTuples:
        shown = page.visible(body_height())
        total = len(page.lines)
        if len(shown) < total:
            text = t("viewer.keys_at", start=shown.start + 1, stop=shown.stop, total=total)
        else:
            text = t("viewer.keys")
        return [("class:footer", f" {text}")]

    bindings = KeyBindings()
    moves: dict[str, int | str] = {
        Keys.Up: -1,
        "k": -1,
        Keys.Down: 1,
        "j": 1,
        Keys.PageUp: "-page",
        "b": "-page",
        Keys.PageDown: "page",
        " ": "page",
        Keys.Home: "-all",
        "g": "-all",
        Keys.End: "all",
        "G": "all",
    }
    for key, move in moves.items():

        @bindings.add(key)
        def _scroll(event: KeyPressEvent, move: int | str = move) -> None:
            height = body_height()
            steps = {"page": height, "-page": -height, "all": len(page.lines), "-all": -len(page.lines)}
            page.scroll(move if isinstance(move, int) else steps[move], height)

    for key in (Keys.Escape, "q", Keys.Enter, Keys.Left):

        @bindings.add(key, eager=True)
        def _close(event: KeyPressEvent) -> None:
            event.app.exit()

    layout = Layout(
        HSplit(
            [
                Window(FormattedTextControl(header), height=2),
                Window(FormattedTextControl(body), wrap_lines=False),
                Window(FormattedTextControl(footer), height=1),
            ]
        )
    )
    app = Application(
        layout=layout, key_bindings=bindings, style=_STYLE, full_screen=True, input=input, output=output
    )
    app.ttimeoutlen = ESC_TIMEOUT
    app.run()
