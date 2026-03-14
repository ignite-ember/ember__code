"""Input handler — manages user input, history, and autocomplete."""

import sys
from typing import TYPE_CHECKING

from ember_code.tui.widgets import InputHistory

if TYPE_CHECKING:
    from ember_code.skills.loader import SkillPool


# ── Platform-aware key labels ────────────────────────────────────

_IS_MACOS = sys.platform == "darwin"


def shortcut_label(key: str) -> str:
    """Return a platform-appropriate shortcut label.

    On macOS: Ctrl+D → ⌃D, on others: Ctrl+D.
    """
    if _IS_MACOS:
        # Map common modifier+key combos to Mac symbols
        if key.startswith("Ctrl+"):
            return f"⌃{key[5:]}"
        if key.startswith("Shift+"):
            return f"⇧{key[6:]}"
    return key


SHORTCUT_HELP = (
    "## Keyboard Shortcuts\n"
    f"- `{shortcut_label('Enter')}` — send message\n"
    f"- `{shortcut_label('Shift+Enter')}` — new line\n"
    f"- `{shortcut_label('Ctrl+D')}` — quit\n"
    f"- `{shortcut_label('Ctrl+L')}` — clear screen\n"
    f"- `{shortcut_label('Ctrl+O')}` — expand/collapse all messages\n"
    f"- `{shortcut_label('Ctrl+V')}` — toggle verbose mode\n"
    f"- `{shortcut_label('Up/Down')}` — input history\n"
    f"- `{shortcut_label('Escape')}` — cancel\n"
)


class AutocompleteProvider:
    """Resolves slash-command completions from built-in commands and skills."""

    BUILTIN_COMMANDS = (
        "/help",
        "/quit",
        "/exit",
        "/agents",
        "/skills",
        "/hooks",
        "/sessions",
        "/rename",
        "/memory",
        "/knowledge",
        "/clear",
        "/config",
    )

    def __init__(self, skill_pool: "SkillPool | None" = None):
        self._skill_pool = skill_pool

    def complete(self, text: str) -> list[str]:
        """Return matching slash commands for the given partial input."""
        if not text.startswith("/") or text.startswith("//"):
            return []
        stripped = text.lstrip("/")
        parts = stripped.split()
        partial = parts[0] if parts else ""
        if not partial:
            return []

        all_commands = list(self.BUILTIN_COMMANDS)
        if self._skill_pool:
            for s in self._skill_pool.list_skills():
                all_commands.append(f"/{s.name}")

        matches = [c for c in all_commands if c.startswith(f"/{partial}")]
        # Don't show completions if the user already typed an exact match
        if f"/{partial}" in matches:
            return []
        return matches[:5]


class InputHandler:
    """Manages the input widget, history navigation, and autocomplete.

    Decoupled from the Textual App so it can be tested independently.
    """

    def __init__(self, skill_pool: "SkillPool | None" = None, max_history: int = 100):
        self.history = InputHistory(max_size=max_history)
        self.autocomplete = AutocompleteProvider(skill_pool)

    def on_submit(self, text: str) -> str | None:
        """Record the submitted text in history.

        Returns the stripped text, or None if empty.
        """
        stripped = text.strip()
        if not stripped:
            return None
        self.history.push(stripped)
        return stripped

    def on_up(self, current_text: str) -> str | None:
        """Navigate up in history."""
        return self.history.navigate_up(current_text)

    def on_down(self) -> str | None:
        """Navigate down in history."""
        return self.history.navigate_down()

    def get_completions(self, text: str) -> list[str]:
        """Get autocomplete suggestions for the current input."""
        return self.autocomplete.complete(text)
