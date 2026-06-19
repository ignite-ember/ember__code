"""Dump the *real* system message Agno sends to the model.

Earlier diagnostic measured our own ``agent.instructions`` strings,
which under-counted the truth: Agno wraps them with description /
role / additional_information / memory framing / cultural knowledge /
tool JSON schemas. This script calls Agno's own ``get_system_message``
so you see exactly what the model receives.

Run::

    .venv/bin/python scripts/debug_prompt_real.py [project_dir]
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


def section(title: str) -> str:
    return f"\n{'─' * 60}\n{title}\n{'─' * 60}"


async def main() -> None:
    project = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    from ember_code.core.config.settings import load_settings
    from ember_code.core.session.core import Session

    settings = load_settings(project_dir=project)
    sess = Session(project_dir=project, settings=settings)

    await asyncio.sleep(0.5)
    agent = sess.main_team

    # Mirror what Agno does on each run. We bypass needing a real
    # session/RunContext by feeding a minimal stub — agent.get_system_message
    # only needs them for state-formatting which we don't use.
    from agno.agent._messages import get_system_message
    from agno.session import AgentSession

    try:
        agent_session = AgentSession(
            session_id="diag", agent_id=agent.id or "ember", session_data={}, runs=[]
        )
    except TypeError:
        agent_session = AgentSession.__new__(AgentSession)

    # Tools as Agno itself would render them for the model.
    resolved_tools: list = []
    try:
        from agno.tools.function import Function
        for t in agent.tools or []:
            if isinstance(t, Function):
                resolved_tools.append(t)
            else:
                # Toolkit → iterate
                fns = getattr(t, "functions", None) or getattr(t, "_functions", None)
                if isinstance(fns, dict):
                    resolved_tools.extend(fns.values())
                elif isinstance(fns, list):
                    resolved_tools.extend(fns)
    except Exception as exc:
        print(f"warn: tool collection failed — {exc}")

    # Disable async-only fetches (memory/culture) — Agno's sync path
    # breaks against an async DB. They contribute a known small block
    # we'll annotate at the bottom.
    _add_mem = agent.add_memories_to_context
    _add_cul = getattr(agent, "add_culture_to_context", False)
    agent.add_memories_to_context = False
    if hasattr(agent, "add_culture_to_context"):
        agent.add_culture_to_context = False
    try:
        sys_msg = get_system_message(agent=agent, session=agent_session, tools=resolved_tools)
    finally:
        agent.add_memories_to_context = _add_mem
        if hasattr(agent, "add_culture_to_context"):
            agent.add_culture_to_context = _add_cul
    sys_content = (sys_msg.content if sys_msg else "") or ""

    # Render tool JSON schemas (this is what's appended to the prompt
    # in many provider integrations; some providers include them via
    # a separate `tools` parameter which is still billed as input).
    tool_blobs: list[dict] = []
    for fn in resolved_tools:
        try:
            d = fn.to_dict() if hasattr(fn, "to_dict") else None
            if d is None:
                d = {"name": getattr(fn, "name", "?"), "desc": str(fn)[:60]}
            tool_blobs.append(d)
        except Exception:
            pass
    tool_json = json.dumps(tool_blobs, ensure_ascii=False)

    sys_chars = len(sys_content)
    tools_chars = len(tool_json)

    # Try a real tokenizer (tiktoken) for proper counts. Fall back to
    # the chars/4 estimate if it isn't installed.
    def count_tokens(s: str) -> int:
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(s))
        except Exception:
            return len(s) // 4

    sys_tok = count_tokens(sys_content)
    tools_tok = count_tokens(tool_json)

    print(f"Project: {project}")
    print(f"Model:   {settings.models.default}")
    print(section("Agno-built system message (what the model literally receives)"))
    print(f"  chars  : {sys_chars:>10,}")
    print(f"  tokens : {sys_tok:>10,}  (tiktoken cl100k_base)")
    print(section(f"Tool JSON schemas ({len(tool_blobs)} fns — billed as input on most providers)"))
    print(f"  chars  : {tools_chars:>10,}")
    print(f"  tokens : {tools_tok:>10,}")
    print(section("Per-turn floor (sys + tools, before any user msg or history)"))
    print(f"  tokens : {sys_tok + tools_tok:>10,}")

    print(section("First 60 lines of the system message"))
    for ln in sys_content.splitlines()[:60]:
        print(f"  {ln}")
    if len(sys_content.splitlines()) > 60:
        print(f"  … +{len(sys_content.splitlines()) - 60} more lines")


asyncio.run(main())
