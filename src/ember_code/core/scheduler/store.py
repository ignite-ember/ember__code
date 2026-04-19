"""SQLite-backed store for scheduled tasks — fully async via aiosqlite."""

import sqlite3
from datetime import datetime
from pathlib import Path

import aiosqlite

from ember_code.core.scheduler.models import ScheduledTask, TaskStatus

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    scheduled_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    result TEXT DEFAULT '',
    error TEXT DEFAULT '',
    recurrence TEXT DEFAULT ''
)
"""

_MIGRATE_RECURRENCE = """
ALTER TABLE scheduled_tasks ADD COLUMN recurrence TEXT DEFAULT ''
"""


class TaskStore:
    """Persists scheduled tasks in SQLite (async)."""

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            db_path = Path.home() / ".ember" / "scheduler.db"
        self._db_path = str(Path(db_path))
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db_sync()

    def _init_db_sync(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(_CREATE_TABLE)
            # Migrate: add recurrence column if missing
            cols = {row[1] for row in conn.execute("PRAGMA table_info(scheduled_tasks)")}
            if "recurrence" not in cols:
                conn.execute(_MIGRATE_RECURRENCE)

    async def add(self, task: ScheduledTask) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO scheduled_tasks
                    (id, description, scheduled_at, created_at, status, result, error, recurrence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.id,
                    task.description,
                    task.scheduled_at.isoformat(),
                    task.created_at.isoformat(),
                    task.status.value,
                    task.result,
                    task.error,
                    task.recurrence,
                ),
            )
            await db.commit()

    async def update_status(
        self, task_id: str, status: TaskStatus, result: str = "", error: str = ""
    ) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE scheduled_tasks SET status = ?, result = ?, error = ? WHERE id = ?",
                (status.value, result, error, task_id),
            )
            await db.commit()

    async def remove(self, task_id: str) -> bool:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
            await db.commit()
            return cursor.rowcount > 0

    async def get_due_tasks(self) -> list[ScheduledTask]:
        """Get all pending tasks whose scheduled time has passed."""
        now = datetime.now().isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "SELECT * FROM scheduled_tasks WHERE status = 'pending' AND scheduled_at <= ? ORDER BY scheduled_at",
                (now,),
            )
            rows = await cursor.fetchall()
        return [self._row_to_task(r) for r in rows]

    async def get_all(self, include_done: bool = False) -> list[ScheduledTask]:
        """Get all tasks, optionally including completed/failed/cancelled."""
        async with aiosqlite.connect(self._db_path) as db:
            if include_done:
                cursor = await db.execute("SELECT * FROM scheduled_tasks ORDER BY scheduled_at")
            else:
                cursor = await db.execute(
                    "SELECT * FROM scheduled_tasks WHERE status IN ('pending', 'running') ORDER BY scheduled_at"
                )
            rows = await cursor.fetchall()
        return [self._row_to_task(r) for r in rows]

    async def get(self, task_id: str) -> ScheduledTask | None:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute("SELECT * FROM scheduled_tasks WHERE id = ?", (task_id,))
            row = await cursor.fetchone()
        return self._row_to_task(row) if row else None

    @staticmethod
    def _row_to_task(row: tuple) -> ScheduledTask:
        return ScheduledTask(
            id=row[0],
            description=row[1],
            scheduled_at=datetime.fromisoformat(row[2]),
            created_at=datetime.fromisoformat(row[3]),
            status=TaskStatus(row[4]),
            result=row[5] or "",
            error=row[6] or "",
            recurrence=row[7] or "" if len(row) > 7 else "",
        )
