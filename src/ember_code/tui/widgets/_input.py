"""Input history and prompt widget for Ember Code TUI."""

from textual.message import Message
from textual.widgets import TextArea


class PromptInput(TextArea):
    """Multiline input: Enter submits, Shift+Enter or \\+Enter inserts a newline.

    Shift+Enter works on terminals that support the kitty keyboard protocol
    (kitty, WezTerm, Ghostty, iTerm2). On other terminals, type \\ then Enter.
    Multiline text can also be pasted directly.
    """

    class Submitted(Message):
        """Posted when the user presses Enter to submit."""

        def __init__(self, text: str) -> None:
            self.text = text
            super().__init__()

    def _on_key(self, event) -> None:
        if event.key == "enter":
            row, col = self.cursor_location
            line = self.document.get_line(row)
            if col > 0 and line[col - 1] == "\\":
                # Backslash + Enter = newline
                event.prevent_default()
                event.stop()
                self.action_delete_left()
                self.insert("\n")
                return
            # Plain Enter = submit
            event.prevent_default()
            event.stop()
            text = self.text.strip()
            if text:
                self.post_message(self.Submitted(text))
            return
        super()._on_key(event)


class InputHistory:
    """Tracks input history for Up/Down arrow navigation."""

    def __init__(self, max_size: int = 100):
        self._history: list[str] = []
        self._index: int = -1
        self._draft: str = ""
        self._max_size = max_size

    @property
    def history(self) -> list[str]:
        return list(self._history)

    def push(self, text: str) -> None:
        """Add an entry to history."""
        text = text.strip()
        if not text:
            return
        # Avoid consecutive duplicates
        if self._history and self._history[-1] == text:
            self._reset_index()
            return
        self._history.append(text)
        if len(self._history) > self._max_size:
            self._history.pop(0)
        self._reset_index()

    def navigate_up(self, current_text: str = "") -> str | None:
        """Move up in history. Returns the history entry or None if at top."""
        if not self._history:
            return None
        if self._index == -1:
            # Entering history — save current input as draft
            self._draft = current_text
            self._index = len(self._history) - 1
        elif self._index > 0:
            self._index -= 1
        else:
            return None  # Already at oldest
        return self._history[self._index]

    def navigate_down(self) -> str | None:
        """Move down in history. Returns the entry, draft, or None."""
        if self._index == -1:
            return None  # Not navigating
        if self._index < len(self._history) - 1:
            self._index += 1
            return self._history[self._index]
        else:
            # Past the newest — restore draft
            draft = self._draft
            self._reset_index()
            return draft

    def _reset_index(self) -> None:
        self._index = -1
        self._draft = ""

    @property
    def is_navigating(self) -> bool:
        return self._index != -1
