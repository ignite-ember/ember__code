"""Dump the FE-facing wire schema to clients/web/src/protocol/wire-schema.json.

Covers (a) every pydantic protocol message and (b) the ad-hoc dict
payloads returned by RPCs the web client consumes. The web test suite
asserts the field names it reads against this file, so a BE rename
breaks a test instead of silently blanking the UI (the DiffRow /
is_ephemeral / loop_status / p.content bug class).

Regenerate after protocol changes:
    uv run python scripts/dump_wire_schema.py
"""

import inspect
import json
from pathlib import Path

from ember_code.protocol import messages as msg

OUT = Path(__file__).resolve().parents[1] / "clients" / "web" / "src" / "protocol" / "wire-schema.json"

# RPC payloads that are plain dicts/dataclasses built by hand in the
# backend — kept in sync manually with the producing code (file noted).
RPC_PAYLOADS = {
    # backend/server.py::loop_status
    "loop_status": [
        "active",
        "paused",
        "prompt",
        "iteration_index",
        "iterations_remaining",
        "cap_explicit",
        "announced_total",
    ],
    # backend/server.py::get_pending_messages
    "pending_message": ["role", "content", "received_at", "message_id"],
    # backend/server.py::get_mcp_server_details
    "mcp_server": [
        "name",
        "connected",
        "transport",
        "tool_names",
        "tool_descriptions",
        "resources",
        "prompts",
        "error",
        "policy_blocked",
    ],
}


def _agent_info_fields() -> list[str]:
    from ember_code.core.pool import AgentInfo

    if hasattr(AgentInfo, "model_fields"):
        return list(AgentInfo.model_fields)
    return [f for f in getattr(AgentInfo, "__dataclass_fields__", {})]


def _scheduled_task_fields() -> list[str]:
    from ember_code.core.scheduler.models import ScheduledTask

    return list(ScheduledTask.model_fields)


def main() -> None:
    schema: dict[str, dict[str, list[str]]] = {"messages": {}, "rpc": {}}

    for _name, cls in inspect.getmembers(msg, inspect.isclass):
        if cls.__module__ != msg.__name__ or not hasattr(cls, "model_fields"):
            continue
        type_field = cls.model_fields.get("type")
        wire_type = getattr(type_field, "default", None) if type_field else None
        key = wire_type if isinstance(wire_type, str) else cls.__name__
        schema["messages"][key] = sorted(cls.model_fields)

    schema["rpc"] = {k: sorted(v) for k, v in RPC_PAYLOADS.items()}
    schema["rpc"]["agent_info"] = sorted(_agent_info_fields())
    schema["rpc"]["scheduled_task"] = sorted(_scheduled_task_fields())

    OUT.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUT} ({len(schema['messages'])} messages, {len(schema['rpc'])} rpc payloads)")


if __name__ == "__main__":
    main()
