"""Task panel widget — shows scheduled/background tasks with expandable details."""

import logging

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from ember_code.scheduler.models import ScheduledTask, TaskStatus

logger = logging.getLogger(__name__)

_STATUS_ICONS = {
    TaskStatus.pending: "[dim]⏳[/dim]",
    TaskStatus.running: "[bold yellow]⚡[/bold yellow]",
    TaskStatus.completed: "[green]✓[/green]",
    TaskStatus.failed: "[red]✗[/red]",
    TaskStatus.cancelled: "[dim]—[/dim]",
}


class TaskPanel(Widget):
    """Bottom-docked interactive task panel with expandable details."""

    can_focus = True

    DEFAULT_CSS = """
    TaskPanel {
        layer: dialog;
        dock: bottom;
        width: 100%;
        height: auto;
        max-height: 60%;
        background: $surface-darken-1;
        border-top: heavy $accent;
        padding: 0 2;
    }

    TaskPanel.-hidden {
        display: none;
    }

    TaskPanel .task-title {
        text-style: bold;
        color: $accent;
    }

    TaskPanel .task-list {
        height: auto;
        max-height: 100%;
        overflow-y: auto;
    }

    TaskPanel .task-entry {
        padding: 0 1;
        height: auto;
    }

    TaskPanel .task-entry.-selected {
        background: $accent;
        color: $text;
    }

    TaskPanel .hint {
        color: $text-muted;
        height: 1;
    }
    """

    class TaskCancelled(Message):
        def __init__(self, task_id: str):
            self.task_id = task_id
            super().__init__()

    class PanelClosed(Message):
        pass

    selected_index: reactive[int] = reactive(0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._tasks: list[ScheduledTask] = []  # all tasks from DB
        self._expanded: set[int] = set()
        self._list_widget: Static | None = None
        self._show_all = True  # False = active only
        self.add_class("-hidden")

    def compose(self) -> ComposeResult:
        yield Static("", classes="task-title", id="task-title")
        with Vertical(classes="task-list", id="task-list"):
            yield Static("", id="task-list-content")
        yield Static("", classes="hint", id="task-hint")

    def on_mount(self) -> None:
        self._list_widget = self.query_one("#task-list-content", Static)

    @property
    def _visible_tasks(self) -> list[ScheduledTask]:
        if self._show_all:
            return self._tasks
        return [t for t in self._tasks if t.status in (TaskStatus.pending, TaskStatus.running)]

    def refresh_tasks(self, tasks: list[ScheduledTask]) -> None:
        """Update the displayed task list, preserving UI state."""
        old_ids = [t.id for t in self._tasks]
        self._tasks = list(tasks)
        new_ids = [t.id for t in self._tasks]

        # Only reset selection/expanded if the task list changed
        if old_ids != new_ids:
            self._expanded.clear()
            visible = self._visible_tasks
            self.selected_index = min(self.selected_index, max(0, len(visible) - 1))

        self._render_all()

    def _render_all(self) -> None:
        if self._list_widget is None:
            return

        visible = self._visible_tasks
        filter_label = "all" if self._show_all else "active"

        # Title
        try:
            title = self.query_one("#task-title", Static)
            if not self._tasks:
                title.update("[bold $accent]Tasks[/bold $accent]  [dim]empty[/dim]")
            else:
                active = sum(
                    1 for t in self._tasks if t.status in (TaskStatus.pending, TaskStatus.running)
                )
                title.update(
                    f"[bold $accent]Tasks[/bold $accent]  "
                    f"[dim]{active} active / {len(self._tasks)} total"
                    f" · showing {filter_label}[/dim]"
                )
        except Exception:
            pass

        # List
        if not visible:
            msg = (
                "[dim]No scheduled tasks. Use /schedule add <task> at <time> to create one.[/dim]"
                if not self._tasks
                else "[dim]No active tasks. Press Tab to show all.[/dim]"
            )
            self._list_widget.update(msg)
        else:
            lines = []
            for i, task in enumerate(visible):
                entry = self._render_entry(i, task)
                if i == self.selected_index:
                    entry = f"[reverse]{entry}[/reverse]"
                lines.append(entry)
            self._list_widget.update("\n".join(lines))

        # Hint
        try:
            hint = self.query_one("#task-hint", Static)
            if self._tasks:
                hint.update(
                    "[dim]↑/↓ navigate · Enter expand/collapse · "
                    "Tab filter · Del cancel · Esc close[/dim]"
                )
            else:
                hint.update("[dim]Esc close[/dim]")
        except Exception:
            pass

    def _render_entry(self, index: int, task: ScheduledTask) -> str:
        icon = _STATUS_ICONS.get(task.status, "?")
        arrow = "▼" if index in self._expanded else "▶"
        time_str = task.scheduled_at.strftime("%Y-%m-%d %H:%M")
        recur = f" [dim]({task.recurrence})[/dim]" if task.recurrence else ""
        desc = task.description[:50] + ("..." if len(task.description) > 50 else "")

        line = f"  {arrow} {icon} [bold]{desc}[/bold]{recur}  [dim]{time_str}[/dim]"

        if index in self._expanded:
            details = f"\n      Description: {task.description}"
            details += f"\n      ID: {task.id}"
            details += f"\n      Status: {task.status.value}"
            details += f"\n      Scheduled: {time_str}"
            details += f"\n      Created: {task.created_at.strftime('%Y-%m-%d %H:%M')}"
            if task.recurrence:
                details += f"\n      Recurrence: {task.recurrence}"
            if task.result:
                details += f"\n      Result: {task.result}"
            if task.error:
                details += f"\n      [red]Error: {task.error}[/red]"
            line += details

        return line

    def watch_selected_index(self, old: int, new: int) -> None:
        self._render_all()

    def on_key(self, event) -> None:
        event.stop()
        event.prevent_default()

        if event.key == "escape":
            self.post_message(self.PanelClosed())
            return

        if event.key == "tab":
            self._show_all = not self._show_all
            self._expanded.clear()
            visible = self._visible_tasks
            self.selected_index = min(self.selected_index, max(0, len(visible) - 1))
            self._render_all()
            return

        visible = self._visible_tasks
        if not visible:
            return

        if event.key == "up":
            self.selected_index = max(0, self.selected_index - 1)
        elif event.key == "down":
            self.selected_index = min(len(visible) - 1, self.selected_index + 1)
        elif event.key == "enter":
            self._toggle_expand()
        elif event.key in ("delete", "backspace") and 0 <= self.selected_index < len(visible):
            task = visible[self.selected_index]
            if task.status in (TaskStatus.pending, TaskStatus.running):
                self.post_message(self.TaskCancelled(task.id))

    def _toggle_expand(self) -> None:
        idx = self.selected_index
        if idx in self._expanded:
            self._expanded.discard(idx)
        else:
            self._expanded.add(idx)
        self._render_all()
