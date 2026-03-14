"""Audit logging — records all tool executions."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ember_code.config.settings import Settings


class AuditLogger:
    """Logs tool executions to a JSON lines file."""

    def __init__(self, settings: Settings):
        self.log_path = Path(settings.storage.audit_log).expanduser()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._enabled = True

    def log(
        self,
        session_id: str,
        agent_name: str,
        tool_name: str,
        status: str = "success",
        details: dict[str, Any] | None = None,
    ):
        """Log a tool execution.

        Args:
            session_id: Current session ID.
            agent_name: Name of the agent making the call.
            tool_name: Name of the tool being called.
            status: Execution status (success, error, blocked).
            details: Additional details (path, command, etc.).
        """
        if not self._enabled:
            return

        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "agent": agent_name,
            "tool": tool_name,
            "status": status,
        }
        if details:
            entry["details"] = details

        try:
            with open(self.log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError:
            pass  # Don't let logging failures break the session

    def log_blocked(
        self,
        session_id: str,
        agent_name: str,
        tool_name: str,
        reason: str,
    ):
        """Log a blocked tool call."""
        self.log(
            session_id=session_id,
            agent_name=agent_name,
            tool_name=tool_name,
            status="BLOCKED",
            details={"reason": reason},
        )
