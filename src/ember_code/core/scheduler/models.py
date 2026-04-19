"""Scheduler data models."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class ScheduledTask(BaseModel):
    """A task scheduled for deferred execution.

    For recurring tasks, ``recurrence`` holds the repeat pattern (e.g.
    "every 1 hours", "daily", "weekly"). After completion, the runner
    creates the next occurrence automatically.
    """

    id: str
    description: str
    scheduled_at: datetime
    created_at: datetime = Field(default_factory=datetime.now)
    status: TaskStatus = TaskStatus.pending
    result: str = ""
    error: str = ""
    recurrence: str = ""  # empty = one-shot, otherwise repeat pattern
