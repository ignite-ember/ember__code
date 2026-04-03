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
_SYNC_COMMANDS_WITH_ARGS: dict[str, Callable[[Session, str], Any]] = {}
_ASYNC_COMMANDS: dict[str, Callable[[Session, str], Coroutine[Any, Any, None]]] = {}


def _register() -> None:
    """Populate command tables (called at module load)."""
    _SYNC_COMMANDS.update(
        {
            "/help": _cmd_help,
            "/agents": _cmd_agents,
            "/skills": _cmd_skills,
            "/clear": _cmd_clear,
            "/config": _cmd_config,
        }
    )
    _SYNC_COMMANDS_WITH_ARGS.update(
        {
            "/hooks": _cmd_hooks,
        }
    )
    _ASYNC_COMMANDS.update(
        {
            "/knowledge": _cmd_knowledge,
            "/sync-knowledge": _cmd_sync_knowledge,
            "/evals": _cmd_evals,
        }
    )


async def dispatch(session: Session, command: str) -> bool:
    """Dispatch a slash command. Returns True if handled."""
    # Split command into base and arguments
    parts = command.strip().split(None, 1)
    base = parts[0] if parts else command
    args = parts[1] if len(parts) > 1 else ""

    if base in _SYNC_COMMANDS:
        _SYNC_COMMANDS[base](session)
        return True
    if base in _SYNC_COMMANDS_WITH_ARGS:
        _SYNC_COMMANDS_WITH_ARGS[base](session, args)
        return True
    if base in _ASYNC_COMMANDS:
        await _ASYNC_COMMANDS[base](session, args)
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
        "- `/hooks` -- list loaded hooks (`/hooks reload` to reload from settings)\n"
        "- `/clear` -- reset conversation context\n"
        "- `/sessions` -- list past sessions\n"
        "- `/config` -- show current settings summary\n"
        "- `/knowledge` -- show knowledge base status\n"
        "- `/knowledge add <url|path|text>` -- add to knowledge base\n"
        "- `/knowledge search <query>` -- search the knowledge base\n"
        "- `/evals [agent]` -- run agent evals (optionally filter by agent name)\n"
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


def _cmd_hooks(session: Session, args: str = "") -> None:
    subcommand = args.strip().lower() if args else ""
    if subcommand == "reload":
        count = session.reload_hooks()
        print_info(f"Hooks reloaded. {count} hook(s) loaded.")
        return

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


async def _cmd_knowledge(session: Session, args: str = "") -> None:
    """Handle /knowledge commands: add, search, status."""
    parts = args.strip().split(None, 1)
    subcommand = parts[0].lower() if parts else ""
    sub_args = parts[1].strip() if len(parts) > 1 else ""

    if subcommand == "add" and sub_args:
        if sub_args.startswith("http://") or sub_args.startswith("https://"):
            result = await session.knowledge_mgr.add(url=sub_args)
        elif "/" in sub_args or sub_args.startswith("."):
            result = await session.knowledge_mgr.add(path=sub_args)
        else:
            result = await session.knowledge_mgr.add(text=sub_args)

        if not result.success:
            print_info(f"Error: {result.error}")
        else:
            print_info(result.message)
        return

    if subcommand == "search" and sub_args:
        response = await session.knowledge_mgr.search(sub_args)
        if not response.results:
            print_info("No results found.")
            return
        lines = [f"## Knowledge Search ({response.total} results)"]
        for i, r in enumerate(response.results, 1):
            name = r.name or "untitled"
            lines.append(f"\n**{i}. {name}**\n{r.content}")
        print_markdown("\n".join(lines))
        return

    # Default: status
    status = session.knowledge_mgr.status()
    if not status.enabled:
        print_info("Knowledge base is disabled. Set knowledge.enabled=true in config.")
        return
    print_markdown(
        "## Knowledge Base\n"
        f"- **Status:** enabled\n"
        f"- **Collection:** {status.collection_name}\n"
        f"- **Documents:** {status.document_count}\n"
        f"- **Embedder:** {status.embedder}\n"
        "\n**Commands:**\n"
        "- `/knowledge add <url>` — add a URL\n"
        "- `/knowledge add <path>` — add a file/directory\n"
        "- `/knowledge add <text>` — add inline text\n"
        "- `/knowledge search <query>` — search the knowledge base\n"
    )


async def _cmd_sync_knowledge(session: Session, _args: str = "") -> None:
    if not session.knowledge_mgr.share_enabled():
        print_info("Knowledge sharing is not enabled. Set knowledge.share=true in config.")
    else:
        results = await session.knowledge_mgr.sync_bidirectional()
        for r in results:
            print_info(f"[{r.direction}] {r.summary}")


async def _cmd_evals(session: Session, args: str = "") -> None:
    from ember_code.evals.reporter import format_results
    from ember_code.evals.runner import SuiteResult

    agent_filter = args.strip() or None
    print_info("Running evals" + (f" for agent '{agent_filter}'" if agent_filter else "") + "...")

    results = await SuiteResult.run_all(
        pool=session.pool,
        settings=session.settings,
        project_dir=session.project_dir,
        agent_filter=agent_filter,
    )

    if not results:
        print_info("No eval suites found. Add YAML files to .ember/evals/")
        return

    report = format_results(results)
    print_markdown(report)


# Populate tables at import time
_register()
