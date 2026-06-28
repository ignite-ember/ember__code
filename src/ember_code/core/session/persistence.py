"""Session persistence — listing, naming, and resuming sessions."""

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)


class SessionPersistence:
    """Handles session listing, naming, and metadata via Agno's DB."""

    def __init__(self, db: Any, session_id: str):
        self.db = db
        self.session_id = session_id

    async def list_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        """List recent sessions from the Agno database."""
        if not self.db:
            return []
        try:
            from agno.db.base import SessionType

            sessions = await self.db.get_sessions(
                session_type=SessionType.AGENT,
                limit=limit,
                sort_by="updated_at",
                sort_order="desc",
                deserialize=True,
            )
            if isinstance(sessions, tuple):
                sessions = sessions[0]

            results = []
            for s in sessions:
                run_count = len(s.runs) if s.runs else 0
                summary = ""
                if s.summary and hasattr(s.summary, "summary"):
                    summary = s.summary.summary or ""
                agent_name = ""
                if s.agent_data and isinstance(s.agent_data, dict):
                    agent_name = s.agent_data.get("name", "")
                name = ""
                if s.session_data and isinstance(s.session_data, dict):
                    name = s.session_data.get("session_name", "")
                results.append(
                    {
                        "session_id": s.session_id,
                        "name": name,
                        "created_at": s.created_at or 0,
                        "updated_at": s.updated_at or 0,
                        "run_count": run_count,
                        "summary": summary,
                        "agent_name": agent_name,
                    }
                )
            return results
        except Exception as exc:
            logger.debug("Failed to list sessions: %s", exc)
            return []

    async def auto_name(self, executor: Any) -> None:
        """Ask Agno to auto-generate a session name from conversation."""
        try:
            if hasattr(executor, "aset_session_name"):
                await executor.aset_session_name(
                    session_id=self.session_id,
                    autogenerate=True,
                )
        except Exception as exc:
            logger.debug("Failed to auto-name session: %s", exc)
            pass

    async def rename(self, new_name: str) -> None:
        """Manually rename the current session."""
        if not self.db:
            return
        try:
            from agno.db.base import SessionType

            await self.db.rename_session(
                session_id=self.session_id,
                session_type=SessionType.AGENT,
                session_name=new_name,
            )
        except Exception as exc:
            logger.debug("Failed to rename session: %s", exc)
            pass

    async def fork(self, name: str | None = None) -> str:
        """Clone the current session under a fresh ``session_id``.

        Reads the source session from Agno's DB, mints a new UUID,
        copies every field (``session_data`` / ``team_data`` /
        ``metadata`` / ``runs`` / ``summary``) under the new id with
        fresh ``created_at`` / ``updated_at`` stamps, optionally
        renames it, and upserts it. Memories aren't copied — they're
        user-scoped on disk so the new session inherits them
        automatically.

        Returns the new ``session_id``. Raises ``RuntimeError`` if no
        DB is configured or the source session can't be loaded.
        """
        if not self.db:
            raise RuntimeError("session store unavailable")
        from agno.db.base import SessionType

        source = await self.db.get_session(
            session_id=self.session_id,
            session_type=SessionType.AGENT,
            deserialize=True,
        )
        if source is None:
            raise RuntimeError(f"source session not found: {self.session_id}")

        # Match the 8-char prefix scheme used elsewhere in the
        # codebase (``core.py``'s fresh-session mint). The full
        # ``uuid.uuid4().hex`` form was correct technically but read
        # as a 32-char wall of hex in the UI.
        new_id = str(uuid.uuid4())[:8]
        now = int(time.time())
        # ``source`` is a freshly-loaded copy from the DB — we own it,
        # so mutating in place is safe. Setting ``session_id`` to the
        # new value means ``upsert_session`` writes a NEW row keyed
        # by the new id (the original row is untouched).
        source.session_id = new_id
        source.created_at = now
        source.updated_at = now
        if name:
            sd = dict(source.session_data or {})
            sd["session_name"] = name
            source.session_data = sd

        await self.db.upsert_session(source, deserialize=True)
        return new_id

    async def get_name(self) -> str:
        """Get the current session's name from the database."""
        if not self.db:
            return ""
        try:
            from agno.db.base import SessionType

            session = await self.db.get_session(
                session_id=self.session_id,
                session_type=SessionType.AGENT,
                deserialize=True,
            )
            if session and session.session_data:
                return session.session_data.get("session_name", "")
        except Exception as exc:
            logger.debug("Failed to get session name: %s", exc)
            pass
        return ""
