"""Modal/overlay widgets: permission dialog, session picker."""

from datetime import datetime

from pydantic import BaseModel
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class SessionInfo(BaseModel):
    """Lightweight session metadata for the picker UI."""

    session_id: str
    name: str = ""
    created_at: int = 0
    updated_at: int = 0
    run_count: int = 0
    summary: str = ""
    agent_name: str = ""

    @property
    def display_name(self) -> str:
        """Session name, falling back to the session_id."""
        return self.name or self.session_id

    @property
    def display_time(self) -> str:
        """Human-readable timestamp."""
        ts = self.updated_at or self.created_at
        if not ts:
            return "unknown"
        dt = datetime.fromtimestamp(ts)
        now = datetime.now()
        delta = now - dt
        if delta.days == 0:
            return dt.strftime("%H:%M")
        if delta.days == 1:
            return "yesterday"
        if delta.days < 7:
            return f"{delta.days}d ago"
        return dt.strftime("%Y-%m-%d")

    @property
    def label(self) -> str:
        """Two-part label: name line + summary line."""
        parts = [f"[bold]{self.display_name}[/bold]"]
        parts.append(f"[dim]{self.display_time}[/dim]")
        if self.run_count:
            parts.append(f"[dim]{self.run_count} runs[/dim]")
        line1 = "  ".join(parts)

        if self.summary:
            short = self.summary[:80]
            if len(self.summary) > 80:
                short += "..."
            return f"{line1}\n    [dim italic]{short}[/dim italic]"
        return line1


class PermissionDialog(Widget):
    """Modal permission prompt with vertical option list.

    Navigate with Up/Down arrows, confirm with Enter.
    """

    _OPTIONS = [
        ("once", "Allow once"),
        ("always", "Always allow"),
        ("similar", "Allow similar"),
        ("deny", "Deny"),
    ]

    DEFAULT_CSS = """
    PermissionDialog {
        layer: dialog;
        align: center middle;
        width: 60;
        height: auto;
        max-height: 20;
        background: $surface;
        border: heavy $warning;
        padding: 1 2;
    }

    PermissionDialog .title {
        text-style: bold;
        color: $warning;
        margin-bottom: 1;
    }

    PermissionDialog .description {
        margin-bottom: 1;
    }

    PermissionDialog .option-list {
        height: auto;
        margin-top: 1;
    }

    PermissionDialog .option {
        padding: 0 1;
        height: 1;
    }

    PermissionDialog .option.-selected {
        background: $accent;
        color: $text;
        text-style: bold;
    }
    """

    class Approved(Message):
        def __init__(self, choice: str):
            self.choice = choice
            super().__init__()

    class Denied(Message):
        pass

    selected_index = reactive(0)

    def __init__(self, tool_name: str, description: str):
        super().__init__()
        self._tool_name = tool_name
        self._description = description

    def compose(self) -> ComposeResult:
        yield Static("Permission Required", classes="title")
        yield Static(f"Tool: [bold]{self._tool_name}[/bold]", classes="description")
        yield Static(self._description, classes="description")
        with Vertical(classes="option-list"):
            for i, (_key, label) in enumerate(self._OPTIONS):
                cls = "option -selected" if i == 0 else "option"
                yield Static(f"  {label}", id=f"opt-{i}", classes=cls)

    def watch_selected_index(self, old: int, new: int) -> None:
        """Update visual selection when index changes."""
        try:
            old_widget = self.query_one(f"#opt-{old}", Static)
            old_widget.remove_class("-selected")
            new_widget = self.query_one(f"#opt-{new}", Static)
            new_widget.add_class("-selected")
        except Exception:
            pass

    def on_key(self, event) -> None:
        if event.key == "up":
            event.prevent_default()
            self.selected_index = max(0, self.selected_index - 1)
        elif event.key == "down":
            event.prevent_default()
            self.selected_index = min(len(self._OPTIONS) - 1, self.selected_index + 1)
        elif event.key == "enter":
            event.prevent_default()
            self._confirm_selection()
        elif event.key == "escape":
            event.prevent_default()
            self.post_message(self.Denied())
            self.remove()

    def on_click(self, event) -> None:
        """Allow clicking an option to select and confirm."""
        for i in range(len(self._OPTIONS)):
            try:
                widget = self.query_one(f"#opt-{i}", Static)
                if widget is event.widget or widget is getattr(event, "_sender", None):
                    self.selected_index = i
                    self._confirm_selection()
                    return
            except Exception:
                pass

    def _confirm_selection(self) -> None:
        key, _label = self._OPTIONS[self.selected_index]
        if key == "deny":
            self.post_message(self.Denied())
        else:
            self.post_message(self.Approved(key))
        self.remove()


class SessionPickerWidget(Widget):
    """Vertical list for selecting a previous session.

    Navigate with Up/Down arrows, confirm with Enter, cancel with Escape.
    """

    DEFAULT_CSS = """
    SessionPickerWidget {
        layer: dialog;
        align: center middle;
        width: 80;
        height: auto;
        max-height: 24;
        background: $surface;
        border: heavy $accent;
        padding: 1 2;
    }

    SessionPickerWidget .picker-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }

    SessionPickerWidget .picker-hint {
        color: $text-muted;
        margin-bottom: 1;
    }

    SessionPickerWidget .session-list {
        height: auto;
        max-height: 16;
        overflow-y: auto;
    }

    SessionPickerWidget .session-entry {
        padding: 0 1;
        height: auto;
    }

    SessionPickerWidget .session-entry.-selected {
        background: $accent;
        color: $text;
        text-style: bold;
    }

    SessionPickerWidget .session-entry.-current {
        color: $success;
    }

    SessionPickerWidget .empty-msg {
        color: $text-muted;
        padding: 1 0;
    }
    """

    class Selected(Message):
        """Posted when the user picks a session."""

        def __init__(self, session_id: str):
            self.session_id = session_id
            super().__init__()

    class Cancelled(Message):
        """Posted when the user cancels the picker."""

        pass

    selected_index = reactive(0)

    def __init__(self, sessions: list[SessionInfo], current_session_id: str = ""):
        super().__init__()
        self._sessions = sessions
        self._current_session_id = current_session_id

    def compose(self) -> ComposeResult:
        yield Static("Select Session", classes="picker-title")
        yield Static(
            "[dim]Up/Down to navigate, Enter to select, Esc to cancel[/dim]",
            classes="picker-hint",
        )
        with Vertical(classes="session-list"):
            if not self._sessions:
                yield Static("No previous sessions found.", classes="empty-msg")
            else:
                for i, info in enumerate(self._sessions):
                    classes = ["session-entry"]
                    if i == 0:
                        classes.append("-selected")
                    if info.session_id == self._current_session_id:
                        classes.append("-current")
                    yield Static(info.label, id=f"sess-{i}", classes=" ".join(classes))

    def watch_selected_index(self, old: int, new: int) -> None:
        try:
            old_widget = self.query_one(f"#sess-{old}", Static)
            old_widget.remove_class("-selected")
            new_widget = self.query_one(f"#sess-{new}", Static)
            new_widget.add_class("-selected")
        except Exception:
            pass

    def on_key(self, event) -> None:
        if not self._sessions:
            if event.key in ("escape", "enter"):
                event.prevent_default()
                self.post_message(self.Cancelled())
                self.remove()
            return

        if event.key == "up":
            event.prevent_default()
            self.selected_index = max(0, self.selected_index - 1)
        elif event.key == "down":
            event.prevent_default()
            self.selected_index = min(len(self._sessions) - 1, self.selected_index + 1)
        elif event.key == "enter":
            event.prevent_default()
            session = self._sessions[self.selected_index]
            self.post_message(self.Selected(session.session_id))
            self.remove()
        elif event.key == "escape":
            event.prevent_default()
            self.post_message(self.Cancelled())
            self.remove()
