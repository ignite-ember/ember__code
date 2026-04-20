"""Live task progress widget — shows task list during tasks-mode execution."""

from pydantic import BaseModel, Field
from textual.widget import Widget
from textual.widgets import Static

_STATUS_ICONS = {
    "pending": "[dim]○[/dim]",
    "in_progress": "[bold yellow]◉[/bold yellow]",
    "completed": "[green]●[/green]",
    "failed": "[red]✗[/red]",
    "blocked": "[dim]◌[/dim]",
}


class TaskItem(BaseModel):
    """Lightweight task data for display."""

    id: str = ""
    title: str = ""
    status: str = "pending"
    assignee: str | None = None
    dependencies: list[str] = Field(default_factory=list)


class TaskProgressWidget(Widget):
    """Inline widget showing live task list during tasks-mode execution.

    Renders as a compact list with status icons that update in real-time
    as TaskCreatedEvent and TaskUpdatedEvent stream in.
    """

    DEFAULT_CSS = """
    TaskProgressWidget {
        height: auto;
        margin: 0 0 0 2;
        padding: 0 1;
        border-left: solid $accent 30%;
    }

    TaskProgressWidget .task-progress-header {
        color: $accent;
        text-style: bold;
        height: 1;
    }

    TaskProgressWidget .task-progress-item {
        height: 1;
    }

    TaskProgressWidget .task-progress-summary {
        color: $text-muted;
        height: 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._tasks: dict[str, TaskItem] = {}
        self._iteration = 0
        self._max_iterations = 0

    def on_task_created(self, task_id: str, title: str, assignee: str | None, status: str) -> None:
        """Called when a new task is created."""
        self._tasks[task_id] = TaskItem(
            id=task_id,
            title=title,
            status=status,
            assignee=assignee,
        )
        self._rebuild()

    def on_task_updated(self, task_id: str, status: str, assignee: str | None = None) -> None:
        """Called when a task status changes."""
        if task_id in self._tasks:
            self._tasks[task_id].status = status
            if assignee is not None:
                self._tasks[task_id].assignee = assignee
        self._rebuild()

    def on_task_state_updated(self, tasks: list) -> None:
        """Called with the full task list from TaskStateUpdatedEvent."""
        for t in tasks:
            tid = getattr(t, "id", "") or getattr(t, "task_id", "")
            if not tid:
                continue
            title = getattr(t, "title", "")
            status = getattr(t, "status", "pending")
            assignee = getattr(t, "assignee", None)
            deps = getattr(t, "dependencies", []) or []
            self._tasks[tid] = TaskItem(
                id=tid,
                title=title,
                status=status,
                assignee=assignee,
                dependencies=deps,
            )
        self._rebuild()

    def on_iteration(self, iteration: int, max_iterations: int) -> None:
        """Called when a new iteration starts."""
        self._iteration = iteration
        self._max_iterations = max_iterations
        self._rebuild()

    def _rebuild(self) -> None:
        self.remove_children()
        if not self._tasks:
            return

        # Header with iteration info
        header = "Tasks"
        if self._iteration:
            header += f" [dim](iteration {self._iteration}"
            if self._max_iterations:
                header += f"/{self._max_iterations}"
            header += ")[/dim]"
        self.mount(Static(header, classes="task-progress-header"))

        # Task list
        for task in self._tasks.values():
            icon = _STATUS_ICONS.get(task.status, "?")
            line = f"  {icon} {task.title}"
            if task.assignee:
                line += f" [dim]→ {task.assignee}[/dim]"
            if task.dependencies:
                deps = ", ".join(task.dependencies)
                line += f" [dim](needs: {deps})[/dim]"
            self.mount(Static(line, classes="task-progress-item"))

        # Summary line
        total = len(self._tasks)
        done = sum(1 for t in self._tasks.values() if t.status == "completed")
        failed = sum(1 for t in self._tasks.values() if t.status == "failed")
        in_prog = sum(1 for t in self._tasks.values() if t.status == "in_progress")

        parts = [f"{done}/{total} done"]
        if in_prog:
            parts.append(f"{in_prog} running")
        if failed:
            parts.append(f"{failed} failed")
        self.mount(Static(f"  [dim]{' · '.join(parts)}[/dim]", classes="task-progress-summary"))
