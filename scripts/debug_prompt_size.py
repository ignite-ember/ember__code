"""Dump the assembled system prompt and tool inventory sizes.

Run::

    .venv/bin/python scripts/debug_prompt_size.py [project_dir]

Prints a per-section character + rough token estimate for the current
session's system prompt + tool catalog so we can see exactly which
block is responsible for huge ``input_tokens``.

This is a diagnostic, not a feature — safe to keep around but doesn't
ship in any UI.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


def chars_to_tokens(n: int) -> int:
    # English/code averages ~4 chars/token; close enough for sanity sizing.
    return n // 4


async def main() -> None:
    project = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    if not project.is_dir():
        print(f"not a directory: {project}")
        sys.exit(1)

    # Set up the same way the BE does at startup.
    from ember_code.core.config.settings import Settings, load_settings
    from ember_code.core.session.core import Session

    settings: Settings = load_settings(project_dir=project)

    sess = Session(
        project_dir=project,
        settings=settings,
    )

    # Wait for any background warm-ups to settle so the codeindex /
    # learning context is fully assembled.
    await asyncio.sleep(0.5)

    agent = sess.main_team
    instructions = list(getattr(agent, "instructions", []) or [])
    sections: list[tuple[str, int]] = []

    for i, ins in enumerate(instructions):
        s = ins if isinstance(ins, str) else str(ins)
        first_line = s.lstrip().splitlines()[0][:60] if s else "(empty)"
        sections.append((f"instructions[{i}]  {first_line!r}", len(s)))

    # Tools catalogue (each tool's schema goes into the model prompt).
    tools = getattr(agent, "tools", []) or []
    tool_chars = 0
    for t in tools:
        try:
            import json

            spec = getattr(t, "to_dict", None)
            if callable(spec):
                tool_chars += len(json.dumps(spec()))
            else:
                tool_chars += len(repr(t))
        except Exception:
            tool_chars += 200  # rough fallback
    sections.append((f"tools ({len(tools)} resolved)", tool_chars))

    # User memories (Learning) — what _learning.abuild_context appends.
    try:
        learning = getattr(sess, "_learning", None)
        if learning is not None:
            ctx = await learning.abuild_context(
                user_id=getattr(sess, "user_id", "default"),
                session_id=getattr(sess, "session_id", "x"),
            )
            sections.append(("learning context (abuild_context)", len(ctx or "")))
    except Exception as exc:
        sections.append((f"learning context — error: {exc}", 0))

    total = sum(n for _, n in sections)

    print(f"Project: {project}")
    print(f"Model:   {settings.models.default}")
    print()
    sections.sort(key=lambda kv: -kv[1])
    width = max(len(k) for k, _ in sections)
    for name, n in sections:
        pct = (n / total * 100) if total else 0
        print(
            f"  {name.ljust(width)}  {n:>7,} chars  ~{chars_to_tokens(n):>6,} tok  ({pct:5.1f}%)"
        )
    print()
    print(f"  TOTAL{' ' * (width - 4)}    {total:>7,} chars  ~{chars_to_tokens(total):>6,} tok")
    print()
    print("Per-turn input also includes conversation history + the actual user")
    print("message — those grow with the chat, not visible here.")

    await sess.close() if hasattr(sess, "close") else None


asyncio.run(main())
