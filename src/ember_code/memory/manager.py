"""Memory and storage setup using Agno backends.

Uses Agno's native ``SqliteDb`` / ``AsyncSqliteDb`` for agent session
persistence (``Agent(db=...)``), and ``Memory`` for user-level memory.
"""

import logging
from pathlib import Path
from typing import Any

from ember_code.config.settings import Settings

logger = logging.getLogger(__name__)


class StorageManager:
    """Factory for Agno-native database and memory backends.

    ``create_db()`` returns an Agno ``AsyncBaseDb`` instance suitable for
    ``Agent(db=...)``.  Uses ``AsyncSqliteDb`` for non-blocking I/O in
    the Textual TUI and async agent execution.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    def create_db(self) -> Any | None:
        """Create an Agno ``BaseDb`` for agent session persistence.

        This is the object passed directly to ``Agent(db=db)``.
        """
        backend = self.settings.storage.backend

        if backend == "sqlite":
            return self._create_sqlite_db()
        elif backend == "postgres":
            return self._create_postgres_db()
        return None

    def create_memory(self) -> Any | None:
        """Create a user memory backend."""
        try:
            from agno.memory.v2.memory import Memory

            if self.settings.storage.backend == "sqlite":
                try:
                    from agno.memory.v2.db.sqlite import SqliteMemoryDb

                    db_path = Path(self.settings.storage.memory_db).expanduser()
                    db_path.parent.mkdir(parents=True, exist_ok=True)
                    return Memory(
                        db=SqliteMemoryDb(
                            table_name="ember_memory",
                            db_file=str(db_path),
                        ),
                    )
                except ImportError:
                    pass
        except ImportError:
            pass
        return None

    def _create_sqlite_db(self) -> Any | None:
        """Create an Agno ``AsyncSqliteDb`` for agent session persistence."""
        try:
            from agno.db.sqlite import AsyncSqliteDb

            db_path = Path(self.settings.storage.session_db).expanduser()
            db_path.parent.mkdir(parents=True, exist_ok=True)
            return AsyncSqliteDb(
                db_file=str(db_path),
                session_table="ember_sessions",
            )
        except ImportError:
            logger.debug("agno.db.sqlite.AsyncSqliteDb not available")
            return None

    def _create_postgres_db(self) -> Any | None:
        """Create an Agno ``PostgresDb`` for agent session persistence."""
        try:
            from agno.db.postgres import PostgresDb

            return PostgresDb(
                session_table="ember_sessions",
                db_url="",
            )
        except ImportError:
            logger.debug("agno.db.postgres.PostgresDb not available")
            return None


def setup_db(settings: Settings) -> Any | None:
    """Create an Agno BaseDb for ``Agent(db=...)``."""
    return StorageManager(settings).create_db()


def setup_memory(settings: Settings) -> Any | None:
    """Create an Agno Memory instance."""
    return StorageManager(settings).create_memory()
