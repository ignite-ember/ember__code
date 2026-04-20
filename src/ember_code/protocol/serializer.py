"""Serialize Agno streaming events into protocol messages.

This is the ONLY module that imports both Agno event types and protocol messages.
It translates Agno's internal event model into the transport-agnostic protocol.
"""

from __future__ import annotations

import logging
from typing import Any

from ember_code.protocol import messages as msg
from ember_code.protocol.agno_events import (
    CONTENT_EVENTS,
    MODEL_COMPLETED_EVENTS,
    REASONING_CONTENT_EVENTS,
    REASONING_EVENTS,
    RUN_COMPLETED_EVENTS,
    RUN_ERROR_EVENTS,
    RUN_PAUSED_EVENTS,
    RUN_STARTED_EVENTS,
    TASK_CREATED_EVENTS,
    TASK_ITERATION_EVENTS,
    TASK_STATE_UPDATED_EVENTS,
    TASK_UPDATED_EVENTS,
    TOOL_COMPLETED_EVENTS,
    TOOL_ERROR_EVENTS,
    TOOL_NAMES,
    TOOL_STARTED_EVENTS,
    extract_result,
    format_tool_args,
)

logger = logging.getLogger(__name__)


def serialize_event(event: Any) -> msg.Message | None:
    """Convert an Agno streaming event to a protocol message.

    Returns None for events that don't need to cross the BE→FE boundary
    (e.g. pre-hook events handled internally by the BE).
    """

    # ── Reasoning content (native) ──
    if isinstance(event, REASONING_CONTENT_EVENTS):
        rc = getattr(event, "reasoning_content", "") or ""
        if rc:
            return msg.ContentDelta(text=rc, is_thinking=True)
        return None

    # ── Content streaming ──
    if isinstance(event, CONTENT_EVENTS):
        content = event.content or ""
        if content:
            return msg.ContentDelta(text=content, is_thinking=False)
        return None

    # ── Tool started ──
    if isinstance(event, TOOL_STARTED_EVENTS):
        tool_exec = event.tool
        raw_name = (tool_exec.tool_name or "tool") if tool_exec else "tool"
        friendly = TOOL_NAMES.get(raw_name, raw_name)
        args_summary = format_tool_args(
            tool_exec.tool_args if tool_exec else None,
            tool_name=raw_name,
        )
        return msg.ToolStarted(
            tool_name=raw_name,
            friendly_name=friendly,
            args_summary=args_summary,
            run_id=str(getattr(event, "run_id", "") or ""),
        )

    # ── Tool completed ──
    if isinstance(event, TOOL_COMPLETED_EVENTS):
        data = extract_result(event)

        return msg.ToolCompleted(
            summary=data.summary,
            full_result=data.full_result,
            has_markup=data.has_markup,
            diff_rows=data.diff_rows,
            run_id=str(getattr(event, "run_id", "") or ""),
        )

    # ── Tool error ──
    if isinstance(event, TOOL_ERROR_EVENTS):
        return msg.ToolError(
            error=str(getattr(event, "error", "Unknown error")),
            run_id=str(getattr(event, "run_id", "") or ""),
        )

    # ── Model completed (tokens) ──
    if isinstance(event, MODEL_COMPLETED_EVENTS):
        return msg.ModelCompleted(
            input_tokens=getattr(event, "input_tokens", 0) or 0,
            output_tokens=getattr(event, "output_tokens", 0) or 0,
            run_id=str(getattr(event, "run_id", "") or ""),
            parent_run_id=str(getattr(event, "parent_run_id", "") or ""),
        )

    # ── Run started ──
    if isinstance(event, RUN_STARTED_EVENTS):
        name = getattr(event, "agent_name", None) or getattr(event, "team_name", None) or ""
        run_id = getattr(event, "run_id", None) or ""
        if name and run_id:
            return msg.RunStarted(
                agent_name=str(name),
                run_id=str(run_id),
                parent_run_id=str(getattr(event, "parent_run_id", "") or ""),
                model=str(getattr(event, "model", "") or ""),
            )
        return None

    # ── Run completed ──
    if isinstance(event, RUN_COMPLETED_EVENTS):
        evt_metrics = getattr(event, "metrics", None)
        return msg.RunCompleted(
            run_id=str(getattr(event, "run_id", "") or ""),
            parent_run_id=str(getattr(event, "parent_run_id", "") or ""),
            input_tokens=getattr(evt_metrics, "input_tokens", 0) or 0 if evt_metrics else 0,
            output_tokens=getattr(evt_metrics, "output_tokens", 0) or 0 if evt_metrics else 0,
        )

    # ── Run error ──
    if isinstance(event, RUN_ERROR_EVENTS):
        return msg.RunError(error=str(getattr(event, "content", "Unknown error")))

    # ── Reasoning started ──
    if isinstance(event, REASONING_EVENTS):
        return msg.ReasoningStarted(run_id=str(getattr(event, "run_id", "") or ""))

    # ── Task orchestration ──
    if isinstance(event, TASK_CREATED_EVENTS):
        return msg.TaskCreated(
            task_id=str(getattr(event, "task_id", "")),
            title=str(getattr(event, "title", "")),
            assignee=str(getattr(event, "assignee", "") or ""),
            status=str(getattr(event, "status", "pending")),
        )

    if isinstance(event, TASK_UPDATED_EVENTS):
        return msg.TaskUpdated(
            task_id=str(getattr(event, "task_id", "")),
            status=str(getattr(event, "status", "")),
            assignee=str(getattr(event, "assignee", "") or ""),
        )

    if isinstance(event, TASK_ITERATION_EVENTS):
        return msg.TaskIteration(
            iteration=getattr(event, "iteration", 0),
            max_iterations=getattr(event, "max_iterations", 0),
        )

    if isinstance(event, TASK_STATE_UPDATED_EVENTS):
        tasks = getattr(event, "tasks", [])
        # Serialize task objects to dicts
        task_dicts = []
        for t in tasks:
            task_dicts.append(
                {
                    "task_id": str(getattr(t, "task_id", "")),
                    "title": str(getattr(t, "title", "")),
                    "status": str(getattr(t, "status", "")),
                    "assignee": str(getattr(t, "assignee", "") or ""),
                }
            )
        return msg.TaskStateUpdated(tasks=task_dicts)

    # ── HITL pause ──
    if isinstance(event, RUN_PAUSED_EVENTS):
        requirements = []
        for req in getattr(event, "active_requirements", []) or []:
            tool_exec = getattr(req, "tool_execution", None)
            requirements.append(
                msg.HITLRequest(
                    requirement_id=str(id(req)),
                    tool_name=str(getattr(tool_exec, "tool_name", "") if tool_exec else ""),
                    friendly_name=TOOL_NAMES.get(
                        str(getattr(tool_exec, "tool_name", "") if tool_exec else ""), ""
                    ),
                    tool_args=dict(getattr(tool_exec, "tool_args", {}) if tool_exec else {}),
                )
            )
        return msg.RunPaused(
            run_id=str(getattr(event, "run_id", "") or ""),
            requirements=requirements,
        )

    # ── Fallback: content-like events ──
    if hasattr(event, "content") and isinstance(getattr(event, "content", None), str):
        content = event.content
        if content:
            return msg.ContentDelta(text=content, is_thinking=False)

    logger.debug("Unserializable Agno event: %s", type(event).__name__)
    return None
