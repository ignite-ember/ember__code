"""Slash command handlers for the interactive session loop."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from ember_code.utils.display import print_info, print_markdown

if TYPE_CHECKING:
    from ember_code.session.core import Session

# Handler type: sync or async callable taking a Session
_Handler = Callable[["Session"], Any]

_SYNC_COMMANDS: dict[str, _Handler] = {}
_ASYNC_COMMANDS: dict[str, Callable[[Session], Coroutine[Any, Any, None]]] = {}


def _register() -> None:
    """Populate command tables (called at module load)."""
    _SYNC_COMMANDS.update(
        {
            "/help": _cmd_help,
            "/agents": _cmd_agents,
            "/skills": _cmd_skills,
            "/hooks": _cmd_hooks,
            "/clear": _cmd_clear,
            "/config": _cmd_config,
        }
    )
    _ASYNC_COMMANDS.update(
        {
            "/sync-knowledge": _cmd_sync_knowledge,
        }
    )


async def dispatch(session: Session, command: str) -> bool:
    """Dispatch a slash command. Returns True if handled."""
    if command in _SYNC_COMMANDS:
        _SYNC_COMMANDS[command](session)
        return True
    if command in _ASYNC_COMMANDS:
        await _ASYNC_COMMANDS[command](session)
        return True
    return False


def _cmd_help(session: Session) -> None:
    skills_list = "\n".join(
        f"- `/{s.name}`{' ' + s.argument_hint if s.argument_hint else ''} -- {s.description[:60]}"
        for s in session.skill_pool.list_skills()
    )
    print_markdown(
        "## Commands\n"
        "- `/help` -- show this help\n"
        "- `/quit` -- exit\n"
        "- `/agents` -- list loaded agents\n"
        "- `/skills` -- list loaded skills\n"
        "- `/hooks` -- list loaded hooks\n"
        "- `/clear` -- reset conversation context\n"
        "- `/sessions` -- list past sessions\n"
        "- `/config` -- show current settings summary\n"
        "- `/sync-knowledge` -- sync knowledge between git file and vector DB\n"
        "\n## Skills\n"
        f"{skills_list or '(no skills loaded)'}\n"
        "\n## Usage\n"
        "- Type any message to chat\n"
        "- Use `/skill-name [args]` to invoke a skill\n"
    )


def _cmd_agents(session: Session) -> None:
    lines = []
    for defn in session.pool.list_agents():
        tools = ", ".join(defn.tools) if defn.tools else "none"
        lines.append(f"- **{defn.name}** -- {defn.description}\n  tools: {tools}")
    print_markdown("## Agents\n" + "\n".join(lines))


def _cmd_skills(session: Session) -> None:
    lines = []
    for skill in session.skill_pool.list_skills():
        hint = f" {skill.argument_hint}" if skill.argument_hint else ""
        lines.append(f"- **/{skill.name}**{hint} -- {skill.description}")
    print_markdown("## Skills\n" + ("\n".join(lines) or "(no skills loaded)"))


def _cmd_hooks(session: Session) -> None:
    if session.hooks_map:
        lines = []
        for event, hook_list in session.hooks_map.items():
            for h in hook_list:
                matcher = f" (matcher: {h.matcher})" if h.matcher else ""
                lines.append(f"- **{event}**: `{h.command or h.url}`{matcher}")
        print_markdown("## Hooks\n" + "\n".join(lines))
    else:
        print_info("No hooks loaded.")


def _cmd_clear(session: Session) -> None:
    session.session_id = str(uuid.uuid4())[:8]
    print_info(f"Conversation cleared. New session: {session.session_id}")


def _cmd_config(session: Session) -> None:
    s = session.settings
    lines = [
        "## Current Configuration",
        "",
        f"**Model:** {s.models.default}",
        "",
        "**Permissions:**",
        f"  file_read={s.permissions.file_read}, file_write={s.permissions.file_write}",
        f"  shell_execute={s.permissions.shell_execute}",
        "",
        f"**Storage backend:** {s.storage.backend}",
        f"**Session DB:** {s.storage.session_db}",
        f"**Audit log:** {s.storage.audit_log}",
        "",
        f"**Orchestration:** max_agents={s.orchestration.max_total_agents}, "
        f"ephemeral={s.orchestration.generate_ephemeral}",
        "",
        f"**Skills auto-trigger:** {s.skills.auto_trigger}",
        f"**Display routing:** {s.display.show_routing}",
        "",
        f"**Project dir:** {session.project_dir}",
        f"**Session ID:** {session.session_id}",
    ]
    print_markdown("\n".join(lines))


async def _cmd_sync_knowledge(session: Session) -> None:
    if not session.knowledge_mgr.share_enabled():
        print_info("Knowledge sharing is not enabled. Set knowledge.share=true in config.")
    else:
        results = await session.knowledge_mgr.sync_bidirectional()
        for r in results:
            print_info(f"[{r.direction}] {r.summary}")


# Populate tables at import time
_register()
