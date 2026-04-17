"""Ember Code TUI — main application.

Thin shell that composes Textual widgets and delegates logic to
``ConversationView``, ``StatusTracker``, ``RunController``,
``HITLHandler``, and ``SessionManager``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
from pathlib import Path
from typing import Any

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.css.query import NoMatches
from textual.events import Resize
from textual.widgets import Static

from ember_code import __version__
from ember_code.config.settings import Settings, load_settings
from ember_code.session import Session
from ember_code.tui.command_handler import CommandHandler, CommandResult
from ember_code.tui.conversation_view import ConversationView
from ember_code.tui.file_index import FileIndex
from ember_code.tui.hitl_handler import HITLHandler
from ember_code.tui.input_handler import InputHandler, extract_at_mention, shortcut_label
from ember_code.tui.run_controller import RunController
from ember_code.tui.session_manager import SessionManager
from ember_code.tui.status_tracker import StatusTracker
from ember_code.tui.widgets import (
    FilePickerDropdown,
    HelpPanelWidget,
    LoginWidget,
    MCPPanelWidget,
    MCPServerInfo,
    MessageWidget,
    ModelPickerWidget,
    PromptInput,
    QueuePanel,
    SessionPickerWidget,
    StatusBar,
    TaskPanel,
    TipBar,
    UpdateBar,
)

logger = logging.getLogger(__name__)


class EmberApp(App):
    """Ember Code Terminal UI Application."""

    TITLE = "Ember Code"
    SUB_TITLE = f"v{__version__}"
    ALLOW_SELECT = True

    CSS = """
    * {
        scrollbar-size: 1 1;
        scrollbar-background: $background;
        scrollbar-color: $text-muted;
    }

    Screen {
        overflow-y: hidden;
        layers: default dialog;
    }

    Markdown .code_inline {
        background: ansi_bright_black;
        color: ansi_green;
    }

    MarkdownFence {
        background: #2b2b2b;
        color: #a9b7c6;
        margin: 1 0;
        padding: 0;
        border: round #323232;
    }

    #header-bar {
        dock: top;
        height: 2;
        width: 100%;
        padding: 1 2 0 2;
        color: $text-muted;
    }

    #conversation {
        height: 1fr;
        overflow-y: auto;
        padding: 1 2;
        scrollbar-size: 1 1;
    }

    #welcome-box {
        height: auto;
        width: 1fr;
        text-align: center;
        margin: 0 4;
        border: round ansi_yellow;
        padding: 0 1;
    }

    #capabilities {
        height: auto;
        width: 1fr;
        margin: 0 4;
        color: $text-muted;
    }

    #footer {
        dock: bottom;
        min-height: 5;
        height: auto;
        width: 100%;
    }

    #prompt-row {
        height: auto;
        width: 100%;
        padding: 0 2;
        border-top: solid ansi_bright_black;
    }

    #prompt-indicator {
        width: 2;
        height: 1;
        color: $accent;
    }

    #user-input {
        width: 1fr;
        height: auto !important;
        min-height: 1;
        max-height: 8;
        border: none !important;
        background: $background;
        color: $text;
        padding: 0;
    }

    #user-input:focus {
        border: none !important;
    }

    #status-bar {
        height: 2;
        width: 100%;
        border-top: solid ansi_bright_black;
        content-align: center middle;
        text-align: center;
        color: $text-muted;
    }

    #tip-bar {
        dock: bottom;
        height: 1;
        width: 100%;
    }

    #update-bar {
        dock: bottom;
        height: auto;
        width: 100%;
    }

    .agent-dispatch {
        height: 1;
        margin: 0 0 0 2;
    }

    .task-event {
        height: 1;
        margin: 0 0 0 2;
    }

    .run-error {
        height: auto;
        margin: 0 0 0 2;
    }

    #queue-panel {
        dock: bottom;
        height: auto;
        max-height: 10;
    }

    #task-panel {
        dock: bottom;
        height: auto;
        max-height: 12;
    }
    """

    _IS_MACOS = sys.platform == "darwin"

    BINDINGS = [
        Binding("ctrl+d", "quit", "Quit", show=False),
        Binding("ctrl+l", "clear_screen", "Clear", show=False),
        Binding("ctrl+o", "toggle_expand_all", "Expand", show=False),
        Binding("ctrl+v", "toggle_verbose", "Verbose", show=False),
        Binding("ctrl+q", "toggle_queue", "Queue", show=False),
        Binding("ctrl+t", "toggle_tasks", "Tasks", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(
        self,
        settings: Settings | None = None,
        resume_session_id: str | None = None,
        initial_message: str | None = None,
        project_dir: Path | None = None,
        additional_dirs: list[Path] | None = None,
        pre_knowledge: Any | None = None,
    ):
        super().__init__()
        self.settings = settings or load_settings()
        self.resume_session_id = resume_session_id
        self.initial_message = initial_message
        self._project_dir = project_dir
        self._additional_dirs = additional_dirs
        self._pre_knowledge = pre_knowledge

        self._session: Session | None = None
        self._conversation: ConversationView | None = None
        self._input_handler: InputHandler | None = None
        self._command_handler: CommandHandler | None = None

        # Managers initialised in on_mount once widgets exist
        self._status: StatusTracker | None = None
        self._controller: RunController | None = None
        self._hitl: HITLHandler | None = None
        self._sessions: SessionManager | None = None
        self._scheduler_runner = None

    # ── Public accessors ────────────────────────────────────────────

    @property
    def session(self) -> Session | None:
        """Public accessor for the current session."""
        return self._session

    @property
    def command_handler(self) -> CommandHandler | None:
        """Public accessor for the command handler."""
        return self._command_handler

    # ── Compose / Mount ───────────────────────────────────────────

    @staticmethod
    def _get_full_name() -> str:
        """Get the user's full name from the system."""
        import subprocess

        try:
            if sys.platform == "darwin":
                result = subprocess.run(
                    ["id", "-F"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip()
            import pwd

            return pwd.getpwuid(os.getuid()).pw_gecos.split(",")[0] or os.getlogin()
        except Exception:
            try:
                return os.getlogin()
            except Exception:
                return ""

    def _build_welcome_content(self) -> str:
        """Build the welcome banner content (border is CSS)."""
        name = self._get_full_name()
        model = self.settings.models.default
        cwd = os.getcwd().replace(os.path.expanduser("~"), "~")

        greeting = f"[bold]Welcome back {name}![/bold]" if name else "[bold]Welcome![/bold]"

        logo_lines = [
            "[bold ansi_bright_red]▐▛███▜▌[/bold ansi_bright_red]",
            "[bold ansi_bright_red]▝▜█████▛▘[/bold ansi_bright_red]",
            "[bold ansi_bright_red] ▘▘ ▝▝ [/bold ansi_bright_red]",
        ]

        info = f"[bold]{model}[/bold]  [dim]·[/dim]  [dim]{cwd}[/dim]"

        lines = ["", greeting, ""] + logo_lines + ["", info, ""]
        return "\n".join(lines)

    @staticmethod
    def _build_capabilities_text() -> str:
        """Short capabilities summary shown below the welcome box."""
        lines = [
            "",
            "  [bold]What I can do:[/bold]",
            "",
            "    [dim]●[/dim]  Understand your entire project and how parts connect",
            "    [dim]●[/dim]  Read, search, and reason across your codebase",
            "    [dim]●[/dim]  Edit files and fix bugs — with your approval",
            "    [dim]●[/dim]  Run commands, tests, and multi-step workflows",
            "",
            "  [dim]Enter to send · \\ + Enter for new line · /help for commands[/dim]",
            "",
        ]
        return "\n".join(lines)

    def compose(self) -> ComposeResult:
        _quit_key = shortcut_label("Ctrl+D")
        yield Static(
            f" [bold]Ember Code[/bold] [dim]v{__version__}[/dim]"
            f"    [dim]/help for commands · {_quit_key} to quit[/dim]",
            id="header-bar",
        )
        yield ScrollableContainer(id="conversation")
        yield QueuePanel(id="queue-panel")
        yield TaskPanel(id="task-panel")
        yield UpdateBar(id="update-bar")
        yield TipBar(id="tip-bar")
        with Vertical(id="footer"):
            with Horizontal(id="prompt-row"):
                yield Static("> ", id="prompt-indicator")
                yield PromptInput(
                    "",
                    id="user-input",
                    compact=True,
                    language=None,
                    soft_wrap=True,
                    show_line_numbers=False,
                    highlight_cursor_line=False,
                    placeholder="Type a message or /help",
                )
            yield StatusBar(id="status-bar")

    async def on_mount(self) -> None:
        # Use ANSI colors so the terminal's own palette is respected
        self.ansi_color = True
        self.theme = "textual-ansi"

        self._session = Session(
            self.settings,
            project_dir=self._project_dir,
            resume_session_id=self.resume_session_id,
            additional_dirs=self._additional_dirs,
            pre_knowledge=self._pre_knowledge,
        )

        container = self.query_one("#conversation", ScrollableContainer)
        self._conversation = ConversationView(container, display_config=self.settings.display)

        # Welcome banner — centered box + capabilities
        await container.mount(Static(self._build_welcome_content(), id="welcome-box"))
        await container.mount(Static(self._build_capabilities_text(), id="capabilities"))

        self._file_index = FileIndex(self._project_dir)
        self._input_handler = InputHandler(self._session.skill_pool, file_index=self._file_index)
        self._command_handler = CommandHandler(self._session)

        # Initialise managers
        self._status = StatusTracker(self)
        from ember_code.config.tool_permissions import ToolPermissions

        self._tool_permissions = ToolPermissions()
        self._hitl = HITLHandler(self, self._conversation, self._tool_permissions)
        self._controller = RunController(
            self,
            self._conversation,
            self._status,
            self._hitl,
            session=self._session,
        )
        self._sessions = SessionManager(
            self,
            self._conversation,
            self._status,
        )

        # Resolve context window for the active model
        from ember_code.config.models import ModelRegistry

        registry = ModelRegistry(self.settings)
        self._status.max_context_tokens = min(
            await registry.aget_context_window(),
            self.settings.models.max_context_window,
        )

        self._status.update_status_bar()

        # Load previous messages if resuming a session
        if self.resume_session_id:
            await self._sessions._load_history(self.resume_session_id)

        # Show a random tip
        self._start_tip_rotation()

        self.query_one("#user-input", PromptInput).focus()

        # ── Scheduler ──────────────────────────────────────────────────
        self._start_scheduler()

        # ── Fire SessionStart hook ────────────────────────────────────
        from ember_code.hooks.events import HookEvent

        asyncio.create_task(
            self._session.hook_executor.execute(
                event=HookEvent.SESSION_START.value,
                payload={"session_id": self._session.session_id},
            )
        )

        # ── Non-blocking background init ──────────────────────────────
        asyncio.create_task(self._check_for_update())
        asyncio.create_task(self._init_mcp_background())
        asyncio.create_task(self._file_index.ensure_loaded())
        asyncio.create_task(self._auto_sync_knowledge())

        if self.initial_message:
            task = asyncio.create_task(
                self._controller.process_message(self.initial_message),
            )
            self._controller.set_current_task(task)

    async def _init_mcp_background(self) -> None:
        """Connect user-configured MCP servers in the background."""
        try:
            await self._session.ensure_mcp()
            for name, connected in self._session.get_mcp_status():
                self._status.set_ide_status(name, connected)
        except Exception as exc:
            logger.debug("MCP background init failed: %s", exc)

    async def _auto_sync_knowledge(self) -> None:
        """Auto-sync knowledge file → DB on startup if enabled."""
        if not self._session:
            return
        settings = self._session.settings
        if (
            not settings.knowledge.enabled
            or not settings.knowledge.share
            or not settings.knowledge.auto_sync
        ):
            return
        if self._session.knowledge is None:
            return
        try:
            result = await self._session.knowledge_mgr.sync_from_file()
            if result.new_entries > 0:
                self._conversation.append_info(
                    f"Knowledge sync: loaded {result.new_entries} entries from git"
                )
        except Exception as e:
            logger.warning("Auto knowledge sync failed: %s", e)
            self._conversation.append_info(f"Knowledge sync failed: {e}")

    async def on_unmount(self) -> None:
        """Clean up scheduler, ephemeral agents, and MCP connections on app exit."""
        import os
        import sys

        # Fire SessionEnd hook
        if self._session:
            from ember_code.hooks.events import HookEvent

            with contextlib.suppress(Exception):
                await self._session.hook_executor.execute(
                    event=HookEvent.SESSION_END.value,
                    payload={"session_id": self._session.session_id},
                )

        if self._scheduler_runner:
            self._scheduler_runner.stop()

        if self._session:
            if self._session.settings.orchestration.auto_cleanup:
                self._session.pool.cleanup_ephemeral()
            # Redirect fd 2 → /dev/null BEFORE disconnecting MCP.
            # MCP stdio cleanup triggers anyio cancel scope errors that
            # print after the TUI exits.  Keep stderr redirected permanently.
            try:
                sys.stderr.flush()
                devnull_fd = os.open(os.devnull, os.O_WRONLY)
                os.dup2(devnull_fd, 2)
                os.close(devnull_fd)
            except OSError:
                pass
            await self._session.mcp_manager.disconnect_all()

    # ── Input events ──────────────────────────────────────────────

    @on(PromptInput.Changed, "#user-input")
    def _on_input_changed(self, event: PromptInput.Changed) -> None:
        text_area = event.text_area
        text = text_area.text

        # ── @file mention detection ──────────────────────────────
        row, col = text_area.cursor_location
        mention_query = extract_at_mention(row, col, text_area.document.get_line)
        if mention_query is not None and self._input_handler:
            matches = self._input_handler.get_file_completions(mention_query)
            self._show_file_picker(matches)
            # Hide slash autocomplete if visible
            with contextlib.suppress(NoMatches):
                self.query_one("#autocomplete", Static).display = False
            return

        # Hide file picker when not in @-mention
        self._hide_file_picker()

        # ── Slash command autocomplete ───────────────────────────
        try:
            widget = self.query_one("#autocomplete", Static)
        except NoMatches:
            widget = None

        if self._input_handler:
            matches = self._input_handler.get_completions(text)
            if matches:
                hint = "  ".join(matches)
                if widget:
                    widget.update(f"[dim]{hint}[/dim]")
                    widget.display = True
                else:
                    self._mount_autocomplete(hint)
                return

        if widget:
            widget.display = False

    def _mount_autocomplete(self, hint: str) -> None:
        try:
            area = self.query_one("#footer", Vertical)
            area.mount(Static(f"[dim]{hint}[/dim]", id="autocomplete"))
        except Exception:
            pass

    # ── File picker helpers ────────────────────────────────────

    def _show_file_picker(self, matches: list[str]) -> None:
        """Show or update the file picker dropdown."""
        input_widget = self.query_one("#user-input", PromptInput)
        input_widget.suppress_submit = True
        try:
            picker = self.query_one(FilePickerDropdown)
            picker.update_matches(matches)
        except NoMatches:
            picker = FilePickerDropdown(matches)
            try:
                footer = self.query_one("#footer", Vertical)
                prompt_row = self.query_one("#prompt-row")
                footer.mount(picker, before=prompt_row)
            except Exception:
                pass

    def _hide_file_picker(self) -> None:
        """Remove the file picker dropdown if present."""
        with contextlib.suppress(NoMatches):
            self.query_one(FilePickerDropdown).remove()
        with contextlib.suppress(NoMatches):
            self.query_one("#user-input", PromptInput).suppress_submit = False

    def _insert_file_mention(self, path: str) -> None:
        """Replace the @query with the selected file path."""
        input_widget = self.query_one("#user-input", PromptInput)
        row, col = input_widget.cursor_location
        line = input_widget.document.get_line(row)

        # Find the @ position by scanning backward
        at_pos = col - 1
        while at_pos >= 0 and line[at_pos] != "@":
            at_pos -= 1

        if at_pos < 0:
            return

        # Rebuild the full text with the replacement
        full_text = input_widget.text
        lines = full_text.split("\n")
        old_line = lines[row]
        # Replace from after @ to cursor position with the full path
        new_line = old_line[: at_pos + 1] + path + " " + old_line[col:]
        lines[row] = new_line
        new_text = "\n".join(lines)

        # Calculate new cursor position (after path + space)
        new_col = at_pos + 1 + len(path) + 1

        input_widget.clear()
        input_widget.insert(new_text)
        input_widget.move_cursor((row, new_col))

    @on(PromptInput.Submitted)
    async def _on_input_submitted(self, event: PromptInput.Submitted) -> None:
        """Handle Enter — PromptInput posts Submitted with the text."""
        input_widget = self.query_one("#user-input", PromptInput)
        if self._input_handler:
            submitted = self._input_handler.on_submit(event.text)
            if submitted:
                input_widget.clear()
                with contextlib.suppress(NoMatches):
                    self.query_one("#autocomplete", Static).display = False
                task = asyncio.create_task(
                    self._controller.process_message(submitted),
                )
                if not self._controller.processing:
                    self._controller.set_current_task(task)

    async def on_key(self, event) -> None:
        try:
            input_widget = self.query_one("#user-input", PromptInput)
        except NoMatches:
            return
        if not input_widget.has_focus:
            return

        # ── File picker navigation (takes priority) ─────────────
        try:
            picker = self.query_one(FilePickerDropdown)
        except NoMatches:
            picker = None

        if picker and picker.has_matches:
            if event.key == "up":
                event.prevent_default()
                event.stop()
                picker.move_up()
                return
            if event.key == "down":
                event.prevent_default()
                event.stop()
                picker.move_down()
                return
            if event.key in ("tab", "enter"):
                event.prevent_default()
                event.stop()
                selected = picker.get_selected()
                if selected:
                    self._insert_file_mention(selected)
                self._hide_file_picker()
                return
            if event.key == "escape":
                event.prevent_default()
                event.stop()
                self._hide_file_picker()
                return

        # ── Input history navigation ─────────────────────────────
        if event.key == "up" and self._input_handler and input_widget.cursor_location[0] == 0:
            entry = self._input_handler.on_up(input_widget.text)
            if entry is not None:
                event.prevent_default()
                input_widget.clear()
                input_widget.insert(entry)
                return

        if event.key == "down" and self._input_handler:
            # Only history-navigate when cursor is on the last line
            last_line = input_widget.text.count("\n")
            if input_widget.cursor_location[0] >= last_line:
                entry = self._input_handler.on_down()
                if entry is not None:
                    event.prevent_default()
                    input_widget.clear()
                    input_widget.insert(entry)
                    return

    # ── Command result rendering ──────────────────────────────────

    def render_command_result(self, result: CommandResult) -> None:
        if result.action == "quit":
            self.exit()
        elif result.action == "clear":
            self._sessions.clear()
            self._conversation.append_info("Conversation cleared.")
        elif result.action == "sessions":
            asyncio.create_task(self._sessions.show_picker())
        elif result.action == "model":
            self._show_model_picker()
        elif result.action == "login":
            self._show_login()
        elif result.action == "logout":
            self._status.set_cloud_status(False)
            self._status.update_status_bar()
            self._conversation.append_info(result.content)
            return
        elif result.action == "help":
            self._show_help_panel()
        elif result.action == "mcp":
            asyncio.create_task(self._show_mcp_panel())
        elif result.action == "schedule":
            asyncio.create_task(self.action_toggle_tasks())
        elif result.action == "run_prompt":
            # Feed skill prompt into the main streaming run loop
            asyncio.create_task(self._controller.process_message(result.content))
        elif result.action == "compact":
            self._sessions.clear()
            self._status.reset()
            self._status.update_context_usage()
            self._status.update_status_bar()
            self.refresh()
            if result.content:
                self._conversation.append_info(
                    f"Context compacted. Summary of previous conversation:\n\n{result.content}"
                )
            else:
                self._conversation.append_info("Context compacted.")
        elif result.kind == "markdown":
            self._conversation.append_markdown(result.content)
        elif result.kind == "info":
            self._conversation.append_info(result.content)
        elif result.kind == "error":
            self._conversation.append_error(result.content)

    # ── Session picker events ─────────────────────────────────────

    @on(SessionPickerWidget.Selected)
    async def _on_session_selected(self, event: SessionPickerWidget.Selected) -> None:
        await self._sessions.switch_to(event.session_id)

    @on(SessionPickerWidget.Cancelled)
    def _on_session_cancelled(self, _event: SessionPickerWidget.Cancelled) -> None:
        self.query_one("#user-input", PromptInput).focus()

    # ── Model picker ────────────────────────────────────────────────

    def _show_model_picker(self) -> None:
        # Only show models that have an API key configured
        models = sorted(
            name
            for name, cfg in self.settings.models.registry.items()
            if cfg.get("api_key") or cfg.get("api_key_env") or cfg.get("api_key_cmd")
        )
        if not models:
            self._conversation.append_error("No models configured with API keys.")
            return
        current = self.settings.models.default
        picker = ModelPickerWidget(models=models, current_model=current)
        self.mount(picker)
        picker.focus()

    @on(ModelPickerWidget.Selected)
    def _on_model_selected(self, event: ModelPickerWidget.Selected) -> None:
        self.settings.models.default = event.model_name
        # Rebuild agent with the new model
        self._session.main_team = self._session._build_main_agent()
        self._status.update_status_bar()
        self._conversation.append_info(f"Switched to model: {event.model_name}")
        self.query_one("#user-input", PromptInput).focus()

    @on(ModelPickerWidget.Cancelled)
    def _on_model_cancelled(self, _event: ModelPickerWidget.Cancelled) -> None:
        self.query_one("#user-input", PromptInput).focus()

    # ── Login ────────────────────────────────────────────────────────

    def _show_login(self) -> None:
        api_url = self.settings.api_url
        widget = LoginWidget(api_url=api_url)
        self.mount(widget)
        widget.focus()

    @on(LoginWidget.LoggedIn)
    def _on_logged_in(self, event: LoginWidget.LoggedIn) -> None:
        # Reload cloud credentials into session and rebuild agent
        if self.session:
            from ember_code.auth.credentials import get_access_token, get_org_id, get_org_name

            creds_file = self.settings.auth.credentials_file
            self.session._cloud_token = get_access_token(creds_file)
            self.session._cloud_org_id = get_org_id(creds_file)
            self.session._cloud_org_name = get_org_name(creds_file)
            self.session.main_team = self.session._build_main_agent()
            self._status.set_cloud_status(True, self.session.cloud_org_name or "")
            self._status.update_status_bar()

        self._conversation.append_info(f"Logged in as {event.email}")
        self.query_one("#user-input", PromptInput).focus()

    @on(LoginWidget.Cancelled)
    def _on_login_cancelled(self, _event: LoginWidget.Cancelled) -> None:
        self.query_one("#user-input", PromptInput).focus()

    # ── MCP panel ───────────────────────────────────────────────────

    def _show_help_panel(self) -> None:
        """Mount the interactive help panel."""
        panel = HelpPanelWidget()
        self.mount(panel)
        panel.focus()

    @on(HelpPanelWidget.PanelClosed)
    def _on_help_panel_closed(self, _event: HelpPanelWidget.PanelClosed) -> None:
        self.query_one("#user-input", PromptInput).focus()

    async def _show_mcp_panel(self) -> None:
        """Gather MCP server info and mount the panel.

        Shows current state without triggering connections — the user
        can toggle individual servers on from the panel itself.
        """
        if not self._session:
            return
        servers = self._build_mcp_server_list()
        panel = MCPPanelWidget(servers=servers)
        self.mount(panel)
        panel.focus()

    def _build_mcp_server_list(self) -> list[MCPServerInfo]:
        mgr = self._session.mcp_manager
        servers: list[MCPServerInfo] = []
        for name in mgr.list_servers():
            config = mgr.configs.get(name)
            connected = name in mgr.list_connected()
            servers.append(
                MCPServerInfo(
                    name=name,
                    connected=connected,
                    transport=config.type if config else "unknown",
                    tool_names=mgr.get_tools(name),
                    tool_descriptions=mgr.get_tool_descriptions(name),
                    error=mgr.get_error(name),
                    policy_blocked=mgr._policy.is_denied(name),
                )
            )
        return servers

    @on(MCPPanelWidget.ServerToggleRequested)
    async def _on_mcp_toggle(self, event: MCPPanelWidget.ServerToggleRequested) -> None:
        if event.enable:
            self._conversation.append_info(f"MCP '{event.name}': connecting...")
            # Connect on Textual's event loop — MCP session must stay on
            # the same loop for tool calls to work.
            asyncio.create_task(self._mcp_connect_async(event.name))
        else:
            try:
                await self._session.mcp_manager.disconnect_one(event.name)
            except Exception as exc:
                logger.debug("MCP disconnect error (non-fatal): %s", exc)
            self._session.rebuild_mcp()
            for name, connected in self._session.get_mcp_status():
                self._status.set_ide_status(name, connected)
            self._conversation.append_info(f"MCP '{event.name}': disconnected")
            try:
                panel = self.query_one(MCPPanelWidget)
                panel.refresh_servers(self._build_mcp_server_list())
            except NoMatches:
                pass

    async def _mcp_connect_async(self, name: str) -> None:
        """Connect MCP server on Textual's event loop.

        The MCP session must stay on the same event loop as tool calls.
        Our _connect_stdio bypasses anyio.open_process (which deadlocks
        in Textual) by using the MCP SDK's stdio_client directly with
        errlog redirected.
        """
        mgr = self._session.mcp_manager
        try:
            client = await mgr.connect(name)
            status = "connected" if client else f"failed: {mgr.get_error(name) or 'unknown error'}"
        except Exception as exc:
            status = f"failed: {exc}"
        self._mcp_connect_done(name, status)

    def _mcp_connect_done(self, name: str, status: str) -> None:
        """Update UI after MCP connection completes (runs on main thread)."""
        self._session.rebuild_mcp()
        for sname, connected in self._session.get_mcp_status():
            self._status.set_ide_status(sname, connected)
        self._conversation.append_info(f"MCP '{name}': {status}")
        try:
            panel = self.query_one(MCPPanelWidget)
            panel.refresh_servers(self._build_mcp_server_list())
        except NoMatches:
            pass

    @on(MCPPanelWidget.PanelClosed)
    def _on_mcp_panel_closed(self, _event: MCPPanelWidget.PanelClosed) -> None:
        self.query_one("#user-input", PromptInput).focus()

    # ── Queue panel events ─────────────────────────────────────────

    @on(QueuePanel.ItemDeleted)
    def _on_queue_item_deleted(self, event: QueuePanel.ItemDeleted) -> None:
        removed = self._controller.dequeue_at(event.index)
        if removed:
            short = removed if len(removed) <= 40 else removed[:37] + "..."
            self._conversation.append_info(f"Removed from queue: {short}")

    @on(QueuePanel.ItemEditRequested)
    def _on_queue_item_edit(self, event: QueuePanel.ItemEditRequested) -> None:
        # Remove the item from the queue and put its text into the input box
        self._controller.dequeue_at(event.index)
        input_widget = self.query_one("#user-input", PromptInput)
        input_widget.clear()
        input_widget.insert(event.text)
        input_widget.focus()

    @on(QueuePanel.PanelClosed)
    def _on_queue_panel_closed(self, _event: QueuePanel.PanelClosed) -> None:
        with contextlib.suppress(NoMatches):
            self.query_one("#queue-panel", QueuePanel).add_class("-hidden")
        self.query_one("#user-input", PromptInput).focus()

    # ── Task panel events ──────────────────────────────────────────

    @on(TaskPanel.TaskCancelled)
    async def _on_task_cancelled(self, event: TaskPanel.TaskCancelled) -> None:
        from ember_code.scheduler.models import TaskStatus
        from ember_code.scheduler.store import TaskStore

        store = TaskStore()
        await store.update_status(event.task_id, TaskStatus.cancelled)
        self._conversation.append_info(f"Cancelled task {event.task_id}")
        await self._refresh_task_panel()

    @on(TaskPanel.PanelClosed)
    def _on_task_panel_closed(self, _event: TaskPanel.PanelClosed) -> None:
        with contextlib.suppress(NoMatches):
            self.query_one("#task-panel", TaskPanel).add_class("-hidden")
        if hasattr(self, "_task_refresh_timer") and self._task_refresh_timer:
            self._task_refresh_timer.stop()
            self._task_refresh_timer = None
        self.query_one("#user-input", PromptInput).focus()

    # ── Scheduler ────────────────────────────────────────────────

    def _start_scheduler(self) -> None:
        """Start the background scheduler runner."""
        from ember_code.scheduler.runner import SchedulerRunner
        from ember_code.scheduler.store import TaskStore

        sched_cfg = self.settings.scheduler
        store = TaskStore()
        self._scheduler_runner = SchedulerRunner(
            store=store,
            execute_fn=self._execute_scheduled_task,
            on_task_started=self._on_scheduled_task_started,
            on_task_completed=self._on_scheduled_task_completed,
            poll_interval=sched_cfg.poll_interval,
            task_timeout=sched_cfg.task_timeout,
            max_concurrent=sched_cfg.max_concurrent,
        )
        self._scheduler_runner.start()

    async def _execute_scheduled_task(self, description: str) -> str:
        """Execute a scheduled task through the AI agent."""
        # Wait for session to be ready (up to 60s)
        for _ in range(60):
            if self._session and getattr(self._session, "main_team", None):
                break
            await asyncio.sleep(1)
        else:
            return "Session not ready after 60s"

        team = self._session.main_team
        run = await team.arun(description, stream=False)
        return run.content if hasattr(run, "content") and run.content else str(run)

    def _on_scheduled_task_started(self, task_id: str, description: str) -> None:
        short = description[:50] + ("..." if len(description) > 50 else "")
        self._conversation.append_info(f"⚡ Running scheduled task `{task_id}`: {short}")
        self.notify(f"Task {task_id} started: {short}", title="Scheduler", timeout=5)
        asyncio.create_task(self._refresh_task_panel())

    def _on_scheduled_task_completed(self, task_id: str, description: str, success: bool) -> None:
        short = description[:50] + ("..." if len(description) > 50 else "")
        if success:
            self._conversation.append(
                Static(
                    f"[green]✓[/green] Task `{task_id}` completed: {short}"
                    f"  [dim]→ /schedule show {task_id}[/dim]",
                    classes="task-event",
                )
            )
            self.notify(
                f"Task {task_id} completed: {short}",
                title="Scheduler",
                severity="information",
                timeout=8,
            )
        else:
            self._conversation.append(
                Static(
                    f"[red]✗[/red] Task `{task_id}` failed: {short}"
                    f"  [dim]→ /schedule show {task_id}[/dim]",
                    classes="task-event",
                )
            )
            self.notify(
                f"Task {task_id} failed: {short}",
                title="Scheduler",
                severity="error",
                timeout=10,
            )
        asyncio.create_task(self._refresh_task_panel())

    async def _refresh_task_panel(self) -> None:
        """Refresh the task panel with current tasks."""
        try:
            from ember_code.scheduler.store import TaskStore

            store = TaskStore()
            tasks = await store.get_all(include_done=True)
            panel = self.query_one("#task-panel", TaskPanel)
            panel.refresh_tasks(tasks)
        except Exception:
            pass

    # ── Actions (Textual keybindings) ─────────────────────────────

    def action_clear_screen(self) -> None:
        self._sessions.clear()

    def action_toggle_expand_all(self) -> None:
        container = self._conversation.container
        widgets = container.query(MessageWidget)
        long_widgets = [w for w in widgets if w.is_long]
        if not long_widgets:
            return
        any_collapsed = any(not w.expanded for w in long_widgets)
        for w in long_widgets:
            w.set_expanded(any_collapsed)

    def action_toggle_queue(self) -> None:
        """Toggle queue panel visibility and focus."""
        try:
            panel = self.query_one("#queue-panel", QueuePanel)
            if panel.has_class("-hidden") and self._controller.queue_size > 0:
                panel.remove_class("-hidden")
                panel.focus()
            else:
                panel.add_class("-hidden")
                self.query_one("#user-input", PromptInput).focus()
        except Exception:
            pass

    async def action_toggle_tasks(self) -> None:
        """Toggle task panel visibility."""
        try:
            panel = self.query_one("#task-panel", TaskPanel)
            if panel.has_class("-hidden"):
                await self._refresh_task_panel()
                panel.remove_class("-hidden")
                panel.focus()
                # Start auto-refresh while panel is open
                if not hasattr(self, "_task_refresh_timer") or self._task_refresh_timer is None:
                    self._task_refresh_timer = self.set_interval(1.0, self._auto_refresh_tasks)
            else:
                panel.add_class("-hidden")
                if hasattr(self, "_task_refresh_timer") and self._task_refresh_timer:
                    self._task_refresh_timer.stop()
                    self._task_refresh_timer = None
                self.query_one("#user-input", PromptInput).focus()
        except Exception:
            pass

    async def _auto_refresh_tasks(self) -> None:
        """Periodic refresh of the task panel while it's visible."""
        try:
            panel = self.query_one("#task-panel", TaskPanel)
            if panel.has_class("-hidden"):
                if hasattr(self, "_task_refresh_timer") and self._task_refresh_timer:
                    self._task_refresh_timer.stop()
                    self._task_refresh_timer = None
                return
            await self._refresh_task_panel()
        except Exception:
            pass

    def action_toggle_verbose(self) -> None:
        self._session.settings.display.show_routing = (
            not self._session.settings.display.show_routing
        )
        state = "on" if self._session.settings.display.show_routing else "off"
        self._conversation.append_info(f"Verbose mode: {state}")

    async def _init_mcp_background(self) -> None:
        """Connect user-configured MCP servers in the background."""
        try:
            await self._session.ensure_mcp()
            for name, connected in self._session.get_mcp_status():
                self._status.set_ide_status(name, connected)
        except Exception:
            pass

    async def _check_for_update(self) -> None:
        """Check for a newer CLI version and update the bar if available."""
        try:
            from ember_code.utils.update_checker import check_for_update

            info = await check_for_update()
            if info.available:
                bar = self.query_one("#update-bar", UpdateBar)
                bar.show_update(
                    current=info.current_version,
                    latest=info.latest_version,
                    url=info.download_url,
                )
        except Exception:
            pass  # never break the app for an update check

    # ── Tips ───────────────────────────────────────────────────────

    _TIPS = [
        "/model — switch the active model",
        "/help — list all commands and shortcuts",
        "/sessions — browse and resume past sessions",
        "/clear — reset conversation context",
        "\\ + Enter inserts a newline",
        "/agents — list loaded agents and their tools",
        "/skills — list available skills",
        "/config — show current settings",
        "/schedule add <task> at <time> — schedule deferred tasks",
        "/mcp — manage MCP server connections",
        "Ctrl+T — toggle the task panel",
    ]

    def _start_tip_rotation(self) -> None:
        import random

        try:
            tip_bar = self.query_one("#tip-bar", TipBar)
            tip_bar.set_tip(random.choice(self._TIPS))
            self.set_interval(30, self._rotate_tip)
        except Exception:
            pass

    def _rotate_tip(self) -> None:
        import random

        try:
            tip_bar = self.query_one("#tip-bar", TipBar)
            tip_bar.set_tip(random.choice(self._TIPS))
        except Exception:
            pass

    async def on_resize(self, event: Resize) -> None:
        """Remove and remount the welcome box so CSS border redraws cleanly."""
        try:
            old_box = self.query_one("#welcome-box", Static)
        except NoMatches:
            return

        await old_box.remove()

        container = self.query_one("#conversation", ScrollableContainer)
        new_box = Static(self._build_welcome_content(), id="welcome-box")
        try:
            caps = self.query_one("#capabilities", Static)
            await container.mount(new_box, before=caps)
        except NoMatches:
            await container.mount(new_box, before=0)

        self.screen.refresh(layout=True)

    def action_cancel(self) -> None:
        self._controller.cancel()
