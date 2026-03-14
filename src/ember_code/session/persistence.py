"""Session persistence — listing, naming, and resuming sessions."""

from typing import Any


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
        except Exception:
            return []

    async def auto_name(self, executor: Any) -> None:
        """Ask Agno to auto-generate a session name from conversation."""
        try:
            if hasattr(executor, "aset_session_name"):
                await executor.aset_session_name(
                    session_id=self.session_id,
                    autogenerate=True,
                )
        except Exception:
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
        except Exception:
            pass

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
        except Exception:
            pass
        return ""
