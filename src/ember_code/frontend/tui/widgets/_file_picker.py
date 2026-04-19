"""File picker dropdown — non-focus-stealing autocomplete for @file mentions."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class FilePickerDropdown(Widget):
    """A dropdown list of file matches that does NOT steal focus.

    Mounted above the input in ``#footer``.  The parent app routes
    Up/Down/Tab/Enter/Escape keys to this widget's public methods.
    """

    can_focus = False

    DEFAULT_CSS = """
    FilePickerDropdown {
        height: auto;
        max-height: 14;
        width: 100%;
        overflow-y: auto;
        padding: 0 2;
        background: $surface;
        border-top: solid ansi_bright_black;
    }

    FilePickerDropdown .fp-header {
        color: $text-muted;
        height: 1;
        padding: 0 0;
    }

    FilePickerDropdown .fp-list {
        height: auto;
    }
    """

    selected_index: reactive[int] = reactive(0)

    def __init__(self, matches: list[str] | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._matches: list[str] = matches or []

    def compose(self) -> ComposeResult:
        yield Static("[dim]Files[/dim]", classes="fp-header")
        yield Static(self._render_list(), id="fp-items", classes="fp-list")

    @property
    def has_matches(self) -> bool:
        return bool(self._matches)

    def update_matches(self, matches: list[str]) -> None:
        self._matches = matches
        self.selected_index = 0
        self._refresh_list()

    def move_up(self) -> None:
        if self._matches and self.selected_index > 0:
            self.selected_index -= 1

    def move_down(self) -> None:
        if self._matches and self.selected_index < len(self._matches) - 1:
            self.selected_index += 1

    def get_selected(self) -> str | None:
        if not self._matches:
            return None
        idx = min(self.selected_index, len(self._matches) - 1)
        return self._matches[idx]

    def watch_selected_index(self, _old: int, _new: int) -> None:
        self._refresh_list()

    def _refresh_list(self) -> None:
        try:
            widget = self.query_one("#fp-items", Static)
            widget.update(self._render_list())
        except Exception:
            pass

    def _render_list(self) -> str:
        if not self._matches:
            return "[dim]  No matching files[/dim]"

        lines: list[str] = []
        for i, path in enumerate(self._matches):
            # Split into directory and filename for readability
            if "/" in path:
                dirname, filename = path.rsplit("/", 1)
                display = f"[dim]{dirname}/[/dim]{filename}"
            else:
                display = path

            if i == self.selected_index:
                lines.append(f"  [reverse] {display} [/reverse]")
            else:
                lines.append(f"  {display}")

        return "\n".join(lines)
