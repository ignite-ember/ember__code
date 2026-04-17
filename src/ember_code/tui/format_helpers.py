"""Format helpers for translating Agno events to TUI-friendly data.

Agno event type tuples, friendly tool names, and formatting functions
used by RunController to render Agno streaming events in the TUI.
"""

import logging
from typing import Any

from agno.run import agent as agent_events
from agno.run import team as team_events

logger = logging.getLogger(__name__)

# ── Agno bug workarounds ─────────────────────────────────────────────

# Workaround 1: Agno's team HITL streaming code calls `run_response.agent_id`
# on a TeamRunOutput (which only has `team_id`). Monkeypatch the missing
# attribute so the event creation doesn't crash.
try:
    from agno.run.team import TeamRunOutput as _TRO

    if not hasattr(_TRO, "agent_id"):
        _TRO.agent_id = None  # type: ignore[attr-defined]
    if not hasattr(_TRO, "agent_name"):
        _TRO.agent_name = None  # type: ignore[attr-defined]
except ImportError:
    pass

# ── Agno event type sets ──────────────────────────────────────────────

CONTENT_EVENTS = (agent_events.RunContentEvent, team_events.RunContentEvent)
TOOL_STARTED_EVENTS = (agent_events.ToolCallStartedEvent, team_events.ToolCallStartedEvent)
TOOL_COMPLETED_EVENTS = (agent_events.ToolCallCompletedEvent, team_events.ToolCallCompletedEvent)
TOOL_ERROR_EVENTS = (agent_events.ToolCallErrorEvent, team_events.ToolCallErrorEvent)
MODEL_COMPLETED_EVENTS = (
    agent_events.ModelRequestCompletedEvent,
    team_events.ModelRequestCompletedEvent,
)
RUN_COMPLETED_EVENTS = (
    agent_events.RunCompletedEvent,
    team_events.RunCompletedEvent,
    agent_events.RunOutput,
    team_events.RunOutput,
)
RUN_STARTED_EVENTS = (agent_events.RunStartedEvent, team_events.RunStartedEvent)
RUN_ERROR_EVENTS = (agent_events.RunErrorEvent, team_events.RunErrorEvent)
REASONING_EVENTS = (agent_events.ReasoningStartedEvent, team_events.ReasoningStartedEvent)
REASONING_CONTENT_EVENTS = (
    agent_events.ReasoningContentDeltaEvent,
    team_events.ReasoningContentDeltaEvent,
)
TASK_CREATED_EVENTS = (team_events.TaskCreatedEvent,)
TASK_UPDATED_EVENTS = (team_events.TaskUpdatedEvent,)
TASK_ITERATION_EVENTS = (team_events.TaskIterationStartedEvent,)
TASK_STATE_UPDATED_EVENTS = (team_events.TaskStateUpdatedEvent,)
RUN_PAUSED_EVENTS = (agent_events.RunPausedEvent, team_events.RunPausedEvent)

# ── Friendly tool names ──────────────────────────────────────────────

TOOL_NAMES = {
    "read_file": "Read",
    "save_file": "Write",
    "edit_file": "Edit",
    "edit_file_replace_all": "Edit",
    "create_file": "Write",
    "run_shell_command": "Bash",
    "grep": "Grep",
    "grep_files": "Grep",
    "grep_count": "Grep",
    "glob_files": "Glob",
    "list_files": "LS",
    "duckduckgo_search": "WebSearch",
    "duckduckgo_news": "WebSearch",
    "fetch_url": "WebFetch",
    "fetch_json": "WebFetch",
    "run_python_code": "Python",
    "spawn_agent": "Agent",
    "spawn_team": "Team",
    "delegate_task_to_member": "Delegate",
    "delegate_task_to_members": "Delegate",
    "search_knowledge_base": "Knowledge",
    "update_user_memory": "Memory",
    "schedule_task": "Schedule",
    "list_scheduled_tasks": "Schedule",
    "cancel_scheduled_task": "Schedule",
}


# ── Formatting helpers ────────────────────────────────────────────────


def format_tool_args(tool_args: dict | None, tool_name: str = "") -> str:
    """Format tool arguments into a short summary string."""
    if not tool_args or not isinstance(tool_args, dict):
        return ""

    # Special formatting for orchestration tools — show full task
    if tool_name in ("spawn_agent", "spawn_team"):
        agent = tool_args.get("agent_name", tool_args.get("agent_names", ""))
        task = str(tool_args.get("task", ""))
        mode = tool_args.get("mode", "")
        parts = [agent]
        if mode:
            parts.append(f"mode={mode}")
        if task:
            parts.append(f'"{task}"')
        return ", ".join(parts)

    parts = []
    for k, v in list(tool_args.items())[:3]:
        val = str(v)
        if len(val) > 30:
            val = val[:27] + "..."
        parts.append(f"{k}={val}")
    return ", ".join(parts)


def _format_edit_diff(tool: Any) -> str | None:
    """Format an Edit tool's old_string/new_string as a colored diff."""
    args = getattr(tool, "tool_args", None)
    if not args or not isinstance(args, dict):
        return None
    old = args.get("old_string", "")
    new = args.get("new_string", "")
    if not old and not new:
        return None

    lines = []
    for line in old.splitlines():
        lines.append(f"[red]- {line}[/red]")
    for line in new.splitlines():
        lines.append(f"[green]+ {line}[/green]")
    return "\n".join(lines)


def extract_result(event: Any) -> tuple[str, str]:
    """Extract (summary, full_result) from a tool completion event."""
    tool = getattr(event, "tool", None)

    timing = ""
    if tool:
        tool_metrics = getattr(tool, "metrics", None)
        if tool_metrics:
            duration = getattr(tool_metrics, "duration", None)
            if duration is not None:
                timing = f"{duration:.2f}s"

    result = getattr(tool, "result", None) if tool else None
    tool_name = getattr(tool, "tool_name", "?") if tool else "?"

    # Debug: log raw tool result
    logger.debug(
        "extract_result [%s]: result type=%s, is_none=%s, len=%d",
        tool_name,
        type(result).__name__,
        result is None,
        len(str(result)) if result is not None else 0,
    )

    # For Edit tools, show a colored diff instead of "Successfully edited"
    if tool_name == "edit_file" and tool:
        diff = _format_edit_diff(tool)
        if diff:
            summary_msg = str(result).strip() if result else "Edited"
            if timing:
                summary_msg = f"{summary_msg}, {timing}"
            return summary_msg, diff

    full_text = str(result).strip() if result else ""
    # MCP tools may return literal "None"/"null" for empty responses
    if full_text in ("None", "null", "undefined"):
        full_text = ""

    summary = ""
    if full_text:
        lines = full_text.splitlines()
        if len(lines) <= 1:
            short = full_text[:80]
            summary = short + ("..." if len(full_text) > 80 else "")
        else:
            summary = f"{len(lines)} lines of output"

    if summary and timing:
        summary = f"{summary}, {timing}"
    elif not summary and timing:
        summary = f"completed in {timing}"

    return summary, full_text
