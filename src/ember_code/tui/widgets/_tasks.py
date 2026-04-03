"""Task panel widget — shows scheduled/background tasks and their status."""

import logging

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
    """Dockable panel showing scheduled tasks and their status."""

    can_focus = True

    DEFAULT_CSS = """
    TaskPanel {
        dock: bottom;
        height: auto;
        max-height: 12;
        border-top: solid $accent;
        padding: 0 1;
    }

    TaskPanel.-hidden {
        display: none;
    }

    TaskPanel .task-header {
        color: $accent;
        text-style: bold;
        height: 1;
    }

    TaskPanel .task-item {
        height: 1;
        padding: 0 1;
    }

    TaskPanel .task-item.-selected {
        background: $accent 30%;
        text-style: bold;
    }

    TaskPanel .task-hint {
        color: $text-muted;
        height: 1;
    }
    """

    class TaskSelected(Message):
        """Posted when user presses Enter on a task to view details."""

        def __init__(self, task_id: str):
            self.task_id = task_id
            super().__init__()

    class TaskCancelled(Message):
        """Posted when user deletes/cancels a task."""

        def __init__(self, task_id: str):
            self.task_id = task_id
            super().__init__()

    class PanelClosed(Message):
        pass

    selected_index = reactive(0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._tasks: list[ScheduledTask] = []
        self.add_class("-hidden")

    def refresh_tasks(self, tasks: list[ScheduledTask]) -> None:
        """Update the displayed task list."""
        self._tasks = list(tasks)
        if not self._tasks:
            self.add_class("-hidden")
            return
        self.remove_class("-hidden")
        self.selected_index = min(self.selected_index, max(0, len(self._tasks) - 1))
        self._rebuild()

    def _rebuild(self) -> None:
        self.remove_children()
        if not self._tasks:
            return

        active = sum(1 for t in self._tasks if t.status in (TaskStatus.pending, TaskStatus.running))
        self.mount(
            Static(
                f"[bold]Tasks ({active} active / {len(self._tasks)} total)[/bold]"
                "  [dim]↑↓ navigate  Enter details  Del cancel  Esc close[/dim]",
                classes="task-header",
            )
        )
        for i, task in enumerate(self._tasks):
            icon = _STATUS_ICONS.get(task.status, "?")
            time_str = task.scheduled_at.strftime("%H:%M")
            recur = f" [dim]({task.recurrence})[/dim]" if task.recurrence else ""
            desc = task.description[:40] + ("..." if len(task.description) > 40 else "")
            cls = "task-item -selected" if i == self.selected_index else "task-item"
            self.mount(
                Static(
                    f"  {icon} `{task.id}` {time_str}{recur} {desc}",
                    id=f"task-{i}",
                    classes=cls,
                )
            )

    def watch_selected_index(self, old: int, new: int) -> None:
        try:
            old_w = self.query_one(f"#task-{old}", Static)
            old_w.remove_class("-selected")
        except Exception as exc:
            logger.debug("Failed to deselect task item #task-%d: %s", old, exc)
        try:
            new_w = self.query_one(f"#task-{new}", Static)
            new_w.add_class("-selected")
        except Exception as exc:
            logger.debug("Failed to select task item #task-%d: %s", new, exc)

    def on_key(self, event) -> None:
        if not self._tasks:
            return
        event.stop()
        event.prevent_default()

        if event.key == "up":
            self.selected_index = max(0, self.selected_index - 1)
        elif event.key == "down":
            self.selected_index = min(len(self._tasks) - 1, self.selected_index + 1)
        elif event.key in ("delete", "backspace"):
            if 0 <= self.selected_index < len(self._tasks):
                task = self._tasks[self.selected_index]
                if task.status in (TaskStatus.pending, TaskStatus.running):
                    self.post_message(self.TaskCancelled(task.id))
        elif event.key == "enter":
            if 0 <= self.selected_index < len(self._tasks):
                self.post_message(self.TaskSelected(self._tasks[self.selected_index].id))
        elif event.key == "escape":
            self.post_message(self.PanelClosed())
