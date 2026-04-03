"""CLI interface for Ember Code."""

import asyncio

import click

from ember_code import __version__


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="Ember Code")
@click.option("--model", default=None, help="Model to use")
@click.option("--verbose", is_flag=True, help="Show routing and reasoning")
@click.option("--quiet", is_flag=True, help="Minimal output")
@click.option("-m", "--message", default=None, help="Single message (non-interactive)")
@click.option("--resume", default=None, required=False, help="Resume session (omit ID for last)")
@click.option("--no-memory", is_flag=True, help="Disable persistent memory")
@click.option("--sandbox", is_flag=True, help="Sandbox shell commands")
@click.option("--read-only", is_flag=True, help="No file modifications")
@click.option("--accept-edits", is_flag=True, help="Auto-approve file edits")
@click.option("--auto-approve", is_flag=True, help="Auto-approve everything")
@click.option(
    "--no-tui", is_flag=True, default=False, help="Use plain Rich CLI instead of Textual TUI"
)
@click.option(
    "-p", "--pipe", is_flag=True, help="Pipe mode: read stdin, write stdout, no interactive UI"
)
@click.option("--no-web", is_flag=True, help="Disable web search/fetch tools")
@click.option("--no-color", is_flag=True, help="Disable color output")
@click.option("--debug", is_flag=True, help="Enable debug logging to ~/.ember/debug.log")
@click.option("--strict", is_flag=True, help="Strict mode: deny all dangerous operations")
@click.option("--worktree", is_flag=True, help="Run in an isolated git worktree")
@click.option(
    "--add-dir",
    multiple=True,
    type=click.Path(exists=True, file_okay=False),
    help="Additional directory to include (can be repeated)",
)
@click.pass_context
def cli(
    ctx,
    model,
    verbose,
    quiet,
    message,
    resume,
    no_memory,
    sandbox,
    read_only,
    accept_edits,
    auto_approve,
    no_tui,
    pipe,
    no_web,
    no_color,
    debug,
    strict,
    worktree,
    add_dir,
):
    """Ember Code — AI coding assistant powered by Agno."""
    ctx.ensure_object(dict)

    # ── Debug logging ──────────────────────────────────────────────
    if debug:
        import logging
        from pathlib import Path

        log_path = Path.home() / ".ember" / "debug.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            filename=str(log_path),
            level=logging.DEBUG,
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
            force=True,
        )
        logging.getLogger("ember_code").setLevel(logging.DEBUG)
        click.echo(f"Debug logging enabled → {log_path}")

    # Build CLI overrides
    cli_overrides = {}
    if model:
        cli_overrides.setdefault("models", {})["default"] = model
    if verbose:
        cli_overrides.setdefault("display", {}).update(
            {
                "show_routing": True,
                "show_reasoning": True,
            }
        )
    if quiet:
        cli_overrides.setdefault("display", {}).update(
            {
                "show_tool_calls": False,
                "show_routing": False,
            }
        )
    if sandbox:
        cli_overrides.setdefault("safety", {})["sandbox_shell"] = True
    if read_only:
        cli_overrides.setdefault("permissions", {}).update(
            {
                "file_write": "deny",
                "shell_execute": "deny",
            }
        )
    if accept_edits:
        cli_overrides.setdefault("permissions", {})["file_write"] = "allow"
    if auto_approve:
        cli_overrides.setdefault("permissions", {}).update(
            {
                "file_write": "allow",
                "shell_execute": "allow",
                "git_push": "allow",
                "git_destructive": "allow",
            }
        )
    if no_memory:
        cli_overrides.setdefault("learning", {})["enabled"] = False
        cli_overrides.setdefault("memory", {})["enable_agentic_memory"] = False
    if no_web:
        cli_overrides.setdefault("permissions", {}).update(
            {
                "web_search": "deny",
                "web_fetch": "deny",
            }
        )
    if strict:
        cli_overrides.setdefault("permissions", {}).update(
            {
                "file_write": "deny",
                "shell_execute": "deny",
                "git_push": "deny",
                "git_destructive": "deny",
            }
        )
        cli_overrides.setdefault("safety", {})["sandbox_shell"] = True

    # Load settings
    from ember_code.config.settings import load_settings

    settings = load_settings(cli_overrides=cli_overrides if cli_overrides else None)
    ctx.obj["settings"] = settings

    if ctx.invoked_subcommand is not None:
        return

    # Determine resume session id
    resume_session_id = resume if resume else None

    # ── Worktree setup ───────────────────────────────────────────
    project_dir = None
    worktree_manager = None

    if worktree:
        from pathlib import Path

        from ember_code.worktree import WorktreeManager

        wm = WorktreeManager(Path.cwd())
        wt_info = wm.create(session_id=resume_session_id)
        project_dir = wt_info.worktree_path
        worktree_manager = wm
        click.echo(f"Worktree: {wt_info.worktree_path} (branch: {wt_info.branch_name})")

    # ── Additional directories ───────────────────────────────────
    additional_dirs = None
    if add_dir:
        from pathlib import Path

        additional_dirs = [Path(d).resolve() for d in add_dir]

    # ── Store for cleanup ────────────────────────────────────────
    ctx.obj["worktree_manager"] = worktree_manager
    ctx.obj["project_dir"] = project_dir
    ctx.obj["additional_dirs"] = additional_dirs

    # -- Pipe mode --
    if pipe:
        import sys

        text = sys.stdin.read().strip()
        if message:
            text = f"{message}\n\n{text}" if text else message
        if not text:
            click.echo("Error: no input provided via stdin or -m", err=True)
            raise SystemExit(1)
        from ember_code.session import run_single_message

        asyncio.run(
            run_single_message(
                settings,
                text,
                resume_session_id=resume_session_id,
                project_dir=project_dir,
                additional_dirs=additional_dirs,
            )
        )
        _worktree_cleanup(worktree_manager)
        return

    # -- Single message mode (non-interactive) --
    if message:
        from ember_code.session import run_single_message

        asyncio.run(
            run_single_message(
                settings,
                message,
                resume_session_id=resume_session_id,
                project_dir=project_dir,
                additional_dirs=additional_dirs,
            )
        )
        _worktree_cleanup(worktree_manager)
        return

    # -- Interactive mode (TUI by default, --no-tui for plain Rich CLI) --
    if no_tui:
        from ember_code.session import run_session_interactive

        asyncio.run(
            run_session_interactive(
                settings,
                resume_session_id=resume_session_id,
                project_dir=project_dir,
                additional_dirs=additional_dirs,
            )
        )
        _worktree_cleanup(worktree_manager)
    else:
        from ember_code.tui import EmberApp

        app = EmberApp(
            settings=settings,
            resume_session_id=resume_session_id,
            project_dir=project_dir,
            additional_dirs=additional_dirs,
        )
        _run_app(app)
        _worktree_cleanup(worktree_manager)


def _run_app(app):
    """Run the Textual app. SSE cleanup errors are silenced in on_unmount."""
    app.run()


def _worktree_cleanup(wm) -> None:
    """Clean up worktree after session ends. Report if changes exist."""
    if wm is None:
        return
    info = wm.info
    if info is None:
        return
    cleaned = wm.cleanup()
    if not cleaned:
        click.echo("\nWorktree preserved (has changes):")
        click.echo(f"  Path:   {info.worktree_path}")
        click.echo(f"  Branch: {info.branch_name}")
        click.echo(f"\nTo merge: git merge {info.branch_name}")
        click.echo(f"To remove: git worktree remove {info.worktree_path}")
    else:
        click.echo("Worktree cleaned up (no changes).")


if __name__ == "__main__":
    cli()
