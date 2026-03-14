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
@click.option("--resume", default=None, is_flag=False, flag_value="last", help="Resume session")
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
@click.option("--strict", is_flag=True, help="Strict mode: deny all dangerous operations")
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
    strict,
):
    """Ember Code — AI coding assistant powered by Agno."""
    ctx.ensure_object(dict)

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

        asyncio.run(run_single_message(settings, text, resume_session_id=resume_session_id))
        return

    # -- Single message mode (non-interactive) --
    if message:
        from ember_code.session import run_single_message

        asyncio.run(run_single_message(settings, message, resume_session_id=resume_session_id))
        return

    # -- Interactive mode (TUI by default, --no-tui for plain Rich CLI) --
    if no_tui:
        from ember_code.session import run_session_interactive

        asyncio.run(run_session_interactive(settings, resume_session_id=resume_session_id))
    else:
        from ember_code.tui import EmberApp

        app = EmberApp(
            settings=settings,
            resume_session_id=resume_session_id,
        )
        app.run()


# -- MCP subcommand --


@cli.group()
@click.pass_context
def mcp(ctx):
    """MCP (Model Context Protocol) server commands."""
    pass


@mcp.command("serve")
@click.option(
    "--transport", default="stdio", type=click.Choice(["stdio", "sse"]), help="Transport type"
)
@click.option("--port", default=3000, type=int, help="Port for SSE transport")
@click.pass_context
def mcp_serve(ctx, transport, port):
    """Start Ember Code as an MCP server."""
    settings = ctx.obj["settings"]
    from ember_code.mcp.server import create_mcp_server

    server = create_mcp_server(settings)
    if server is None:
        click.echo("Error: MCP dependencies not installed. Run: pip install mcp", err=True)
        raise SystemExit(1)

    click.echo(f"Starting MCP server (transport={transport})...")
    if transport == "stdio":
        asyncio.run(_run_mcp_stdio(server))
    else:
        click.echo(f"SSE transport on port {port} — not yet implemented.", err=True)
        raise SystemExit(1)


async def _run_mcp_stdio(server):
    """Run MCP server with stdio transport."""
    try:
        from mcp.server.stdio import stdio_server

        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream)
    except ImportError:
        import click as _click

        _click.echo("Error: MCP stdio transport not available.", err=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    cli()
