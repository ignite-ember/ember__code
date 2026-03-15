"""Ember Code TUI — main application.

Thin shell that composes Textual widgets and delegates logic to
``ConversationView``, ``StatusTracker``, ``ExecutionManager``,
``HITLHandler``, and ``SessionManager``.
"""

import asyncio
import contextlib
import os
import sys

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
from ember_code.tui.execution_manager import ExecutionManager
from ember_code.tui.hitl_handler import HITLHandler
from ember_code.tui.input_handler import InputHandler
from ember_code.tui.session_manager import SessionManager
from ember_code.tui.status_tracker import StatusTracker
from ember_code.tui.widgets import (
    MessageWidget,
    PromptInput,
    QueuePanel,
    SessionPickerWidget,
    StatusBar,
    TipBar,
    UpdateBar,
)


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
    }

    Markdown .code_inline {
        background: ansi_bright_black;
        color: $text;
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
        padding: 1 2;
        border: round ansi_yellow;
        text-align: center;
        margin: 0 4;
    }

    #capabilities {
        height: auto;
        width: 1fr;
        margin: 0 4;
        color: $text-muted;
    }

    #footer {
        dock: bottom;
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
        height: auto;
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

    #footer-sep {
        height: auto;
        width: 100%;
        border-bottom: solid ansi_bright_black;
    }

    #status-bar {
        height: 1;
        width: 100%;
        color: $text-muted;
        text-align: center;
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
    """

    _IS_MACOS = sys.platform == "darwin"

    BINDINGS = [
        Binding("ctrl+d", "quit", "Quit", show=False),
        Binding("ctrl+l", "clear_screen", "Clear", show=False),
        Binding("ctrl+o", "toggle_expand_all", "Expand", show=False),
        Binding("ctrl+v", "toggle_verbose", "Verbose", show=False),
        Binding("ctrl+q", "toggle_queue", "Queue", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(
        self,
        settings: Settings | None = None,
        resume_session_id: str | None = None,
        initial_message: str | None = None,
    ):
        super().__init__()
        self.settings = settings or load_settings()
        self.resume_session_id = resume_session_id
        self.initial_message = initial_message

        self._session: Session | None = None
        self._conversation: ConversationView | None = None
        self._input_handler: InputHandler | None = None
        self._command_handler: CommandHandler | None = None

        # Managers initialised in on_mount once widgets exist
        self._status: StatusTracker | None = None
        self._execution: ExecutionManager | None = None
        self._hitl: HITLHandler | None = None
        self._sessions: SessionManager | None = None

    # ── Compose / Mount ───────────────────────────────────────────

    @staticmethod
    def _get_full_name() -> str:
        """Get the user's full name from the system."""
        import subprocess
        try:
            if sys.platform == "darwin":
                result = subprocess.run(
                    ["id", "-F"], capture_output=True, text=True, timeout=2,
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

    def _build_welcome_banner(self) -> str:
        """Build a centered welcome banner like Claude Code."""
        name = self._get_full_name()
        model = self.settings.models.default
        cwd = os.getcwd().replace(os.path.expanduser("~"), "~")

        # Ember logo (small flame-inspired)
        logo_lines = [
            "▐▛███▜▌",
            "▝▜█████▛▘",
            " ▘▘ ▝▝ ",
        ]

        greeting = f"[bold]Welcome back {name}![/bold]" if name else "[bold]Welcome![/bold]"

        lines = ["", greeting, ""]
        for l in logo_lines:
            lines.append(f"[bold ansi_bright_red]{l}[/bold ansi_bright_red]")
        lines += [
            "",
            f"[bold]{model}[/bold]  [dim]·[/dim]  [dim]{cwd}[/dim]",
            "",
        ]
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
        _quit_key = "Ctrl+D"
        yield Static(
            f" [bold]Ember Code[/bold] [dim]v{__version__}[/dim]"
            f"    [dim]/help for commands · {_quit_key} to quit[/dim]",
            id="header-bar",
        )
        yield ScrollableContainer(id="conversation")
        yield QueuePanel(id="queue-panel")
        yield UpdateBar(id="update-bar")
        yield TipBar(id="tip-bar")
        with Vertical(id="footer"):
            with Horizontal(id="prompt-row"):
                yield Static("> ", id="prompt-indicator")
                yield PromptInput(
                    "", id="user-input", compact=True, language=None,
                    soft_wrap=True, show_line_numbers=False,
                    highlight_cursor_line=False,
                    placeholder="Type a message or /help",
                )
            yield Static("", id="footer-sep")
            yield StatusBar(id="status-bar")

    async def on_mount(self) -> None:
        # Use ANSI colors so the terminal's own palette is respected
        self.ansi_color = True
        self.theme = "textual-ansi"

        self._session = Session(
            self.settings,
            resume_session_id=self.resume_session_id,
        )

        container = self.query_one("#conversation", ScrollableContainer)
        self._conversation = ConversationView(container)

        # Welcome banner — centered box + capabilities
        await container.mount(
            Static(self._build_welcome_banner(), id="welcome-box")
        )
        await container.mount(
            Static(self._build_capabilities_text(), id="capabilities")
        )

        self._input_handler = InputHandler(self._session.skill_pool)
        self._command_handler = CommandHandler(self._session)

        # Initialise managers
        self._status = StatusTracker(self)
        self._hitl = HITLHandler(self, self._conversation)
        self._execution = ExecutionManager(
            self,
            self._conversation,
            self._status,
            self._hitl,
        )
        self._sessions = SessionManager(
            self,
            self._conversation,
            self._status,
        )

        # Resolve context window for the active model
        from ember_code.config.models import ModelRegistry

        registry = ModelRegistry(self.settings)
        self._status.max_context_tokens = await registry.aget_context_window()

        self._status.update_status_bar()

        self.query_one("#user-input", PromptInput).focus()

        # ── Check for updates (non-blocking) ─────────────────────────
        asyncio.create_task(self._check_for_update())

        if self.initial_message:
            task = asyncio.create_task(
                self._execution.process_message(self.initial_message),
            )
            self._execution.current_task = task

    # ── Input events ──────────────────────────────────────────────

    @on(PromptInput.Changed, "#user-input")
    def _on_input_changed(self, event: PromptInput.Changed) -> None:
        text = event.text_area.text
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
                    self._execution.process_message(submitted),
                )
                if not self._execution.processing:
                    self._execution.current_task = task

    async def on_key(self, event) -> None:
        try:
            input_widget = self.query_one("#user-input", PromptInput)
        except NoMatches:
            return
        if not input_widget.has_focus:
            return

        if event.key == "up" and self._input_handler:
            # Only history-navigate when cursor is on the first line
            if input_widget.cursor_location[0] == 0:
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

    def _render_command_result(self, result: CommandResult) -> None:
        if result.action == "quit":
            self.exit()
        elif result.action == "clear":
            self._sessions.clear()
            self._conversation.append_info("Conversation cleared.")
        elif result.action == "sessions":
            asyncio.create_task(self._sessions.show_picker())
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

    # ── Queue panel events ─────────────────────────────────────────

    @on(QueuePanel.ItemDeleted)
    def _on_queue_item_deleted(self, event: QueuePanel.ItemDeleted) -> None:
        removed = self._execution.dequeue_at(event.index)
        if removed:
            short = removed if len(removed) <= 40 else removed[:37] + "..."
            self._conversation.append_info(f"Removed from queue: {short}")

    @on(QueuePanel.ItemEditRequested)
    def _on_queue_item_edit(self, event: QueuePanel.ItemEditRequested) -> None:
        # Remove the item from the queue and put its text into the input box
        self._execution.dequeue_at(event.index)
        input_widget = self.query_one("#user-input", PromptInput)
        input_widget.clear()
        input_widget.insert(event.text)
        input_widget.focus()

    @on(QueuePanel.PanelClosed)
    def _on_queue_panel_closed(self, _event: QueuePanel.PanelClosed) -> None:
        with contextlib.suppress(NoMatches):
            self.query_one("#queue-panel", QueuePanel).add_class("-hidden")
        self.query_one("#user-input", PromptInput).focus()

    # ── Actions (Textual keybindings) ─────────────────────────────

    def action_clear_screen(self) -> None:
        self._sessions.clear()

    def action_toggle_expand_all(self) -> None:
        container = self._conversation.container
        widgets = container.query(MessageWidget)
        long_widgets = [w for w in widgets if w._is_long]
        if not long_widgets:
            return
        any_collapsed = any(not w.expanded for w in long_widgets)
        for w in long_widgets:
            w.set_expanded(any_collapsed)

    def action_toggle_queue(self) -> None:
        """Toggle queue panel visibility and focus."""
        try:
            panel = self.query_one("#queue-panel", QueuePanel)
            if panel.has_class("-hidden") and self._execution.queue_size > 0:
                panel.remove_class("-hidden")
                panel.focus()
            else:
                panel.add_class("-hidden")
                self.query_one("#user-input", PromptInput).focus()
        except Exception:
            pass

    def action_toggle_verbose(self) -> None:
        self._session.settings.display.show_routing = (
            not self._session.settings.display.show_routing
        )
        state = "on" if self._session.settings.display.show_routing else "off"
        self._conversation.append_info(f"Verbose mode: {state}")

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

    async def on_resize(self, event: Resize) -> None:
        """Refresh the welcome box on terminal resize."""
        try:
            welcome = self.query_one("#welcome-box", Static)
            welcome.update(self._build_welcome_banner())
        except NoMatches:
            pass

    def action_cancel(self) -> None:
        self._execution.cancel()
