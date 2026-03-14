"""Interactive session loop — REPL for Ember Code."""

import time

from rich.prompt import Prompt

from ember_code import __version__
from ember_code.config.settings import Settings
from ember_code.hooks.events import HookEvent
from ember_code.session.commands import dispatch
from ember_code.session.core import Session
from ember_code.utils.display import (
    print_error,
    print_info,
    print_response,
    print_run_stats,
    print_warning,
    print_welcome,
)


async def run_session_interactive(
    settings: Settings,
    resume_session_id: str | None = None,
):
    """Run an interactive session loop."""

    session = Session(
        settings,
        resume_session_id=resume_session_id,
    )

    # ── Hook: SessionStart ──────────────────────────────────────────
    await session.hook_executor.execute(
        event=HookEvent.SESSION_START.value,
        payload={"session_id": session.session_id},
    )

    # ── Knowledge sync: file → DB (load shared knowledge) ────────
    if session.settings.knowledge.share and session.settings.knowledge.auto_sync:
        sync_result = await session.knowledge_mgr.sync_from_file()
        if sync_result.new_entries > 0:
            print_info(f"Knowledge sync: loaded {sync_result.new_entries} new entries from git")
        elif sync_result.error:
            print_error(f"Knowledge sync error: {sync_result.error}")

    print_welcome(__version__)

    # ── Contextual tip ─────────────────────────────────────────────
    from ember_code.utils.tips import get_tip

    print_info(f"Tip: {get_tip(settings, session.project_dir)}")

    # ── Update check (non-blocking, best-effort) ─────────────────
    try:
        from ember_code.utils.update_checker import check_for_update

        update_info = await check_for_update()
        if update_info.available:
            print_warning(update_info.message)
    except Exception:
        pass

    pool_info = session.pool.agent_names
    if pool_info:
        print_info(f"Loaded agents: {', '.join(pool_info)}")

    skill_names = [s.name for s in session.skill_pool.list_skills()]
    if skill_names:
        print_info(f"Loaded skills: {', '.join('/' + n for n in skill_names)}")

    hook_count = sum(len(v) for v in session.hooks_map.values())
    if hook_count:
        print_info(f"Loaded hooks: {hook_count}")

    if resume_session_id:
        print_info(f"Session: {session.session_id} (resumed)")
    else:
        print_info(f"Session: {session.session_id}")

    while True:
        try:
            message = Prompt.ask("\n[bold blue]>[/bold blue]")

            if not message.strip():
                continue

            stripped = message.strip()

            # ── Quit ────────────────────────────────────────────────
            if stripped.lower() in ("/quit", "/exit", "quit", "exit"):
                print_info("Goodbye!")
                break

            # ── Slash commands ──────────────────────────────────────
            if stripped.startswith("/") and await dispatch(session, stripped):
                continue

            # ── Skill invocation (/skill-name args) ─────────────────
            skill_match = session.skill_pool.match_user_command(stripped)
            if skill_match:
                skill, args = skill_match
                print_info(f"Running skill: /{skill.name}")
                from ember_code.skills.executor import execute_skill

                result = await execute_skill(skill, args, session.pool, session.settings)
                print_response(result)

                session.audit.log(
                    session_id=session.session_id,
                    agent_name="skill",
                    tool_name=f"/{skill.name}",
                    status="success",
                    details={"args": args},
                )
                continue

            # ── Handle the message via orchestrator ─────────────────
            start_time = time.monotonic()
            response = await session.handle_message(message)
            elapsed = time.monotonic() - start_time
            print_response(response)
            print_run_stats(
                elapsed_seconds=elapsed,
                model=session.settings.models.default,
            )

        except KeyboardInterrupt:
            print_info("\nGoodbye!")
            break
        except EOFError:
            break

    # ── Knowledge sync: DB → file (export for git) ─────────────────
    if session.settings.knowledge.share and session.settings.knowledge.auto_sync:
        sync_result = session.knowledge_mgr.sync_to_file()
        if sync_result.new_entries > 0:
            print_info(
                f"Knowledge sync: exported {sync_result.new_entries} new entries to "
                f"{session.settings.knowledge.share_file}"
            )

    # ── Hook: SessionEnd ────────────────────────────────────────────
    await session.hook_executor.execute(
        event=HookEvent.SESSION_END.value,
        payload={"session_id": session.session_id},
    )
