"""Ember Code TUI — main application.

Thin shell that composes Textual widgets and delegates logic to
``ConversationView``, ``StatusTracker``, ``ExecutionManager``,
``HITLHandler``, and ``SessionManager``.
"""

import asyncio
import contextlib
import sys

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import ScrollableContainer, Vertical
from textual.css.query import NoMatches
from textual.widgets import (
    Footer,
    Header,
    Static,
    TextArea,
)

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
    QueuePanel,
    SessionPickerWidget,
    StatusBar,
    TipBar,
    UpdateBar,
    WelcomeBanner,
)


class EmberApp(App):
    """Ember Code Terminal UI Application."""

    TITLE = "Ember Code"
    SUB_TITLE = f"v{__version__}"

    CSS = """
    #conversation {
        height: 1fr;
        overflow-y: auto;
        padding: 0 1;
    }

    #input-area {
        dock: bottom;
        height: auto;
        max-height: 10;
        padding: 0 1;
    }

    #user-input {
        height: auto;
        min-height: 1;
        max-height: 8;
    }

    .user-message {
        background: $surface;
        padding: 0 1;
        margin: 0 0 1 0;
    }

    .assistant-message {
        padding: 0 1;
        margin: 0 0 1 0;
    }

    .error-message {
        color: $error;
        padding: 0 1;
    }

    .info-message {
        color: $text-muted;
        padding: 0 1;
    }

    #status-bar {
        dock: bottom;
        height: 1;
        background: $primary-background;
        color: $text-muted;
        padding: 0 1;
    }

    #tip-bar {
        dock: bottom;
        height: 1;
    }

    #update-bar {
        dock: bottom;
        height: auto;
    }

    #queue-panel {
        dock: bottom;
        height: auto;
        max-height: 10;
    }
    """

    _IS_MACOS = sys.platform == "darwin"

    BINDINGS = [
        Binding("ctrl+d", "quit", "Quit", show=True),
        Binding("ctrl+l", "clear_screen", "Clear", show=True),
        Binding("ctrl+o", "toggle_expand_all", "Expand", show=True),
        Binding("ctrl+v", "toggle_verbose", "Verbose", show=True),
        Binding("ctrl+q", "toggle_queue", "Queue", show=True),
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

    def compose(self) -> ComposeResult:
        yield Header()
        with ScrollableContainer(id="conversation"):
            yield WelcomeBanner()
        yield QueuePanel(id="queue-panel")
        yield UpdateBar(id="update-bar")
        yield TipBar(id="tip-bar")
        yield StatusBar(id="status-bar")
        with Vertical(id="input-area"):
            yield TextArea(id="user-input")
        yield Footer()

    async def on_mount(self) -> None:
        self._session = Session(
            self.settings,
            resume_session_id=self.resume_session_id,
        )

        container = self.query_one("#conversation", ScrollableContainer)
        self._conversation = ConversationView(container)
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

        agents = self._session.pool.agent_names
        if agents:
            self._conversation.append_info(f"Agents: {', '.join(agents)}")

        skills = [s.name for s in self._session.skill_pool.list_skills()]
        if skills:
            self._conversation.append_info(f"Skills: {', '.join('/' + n for n in skills)}")

        self._conversation.append_info(f"Session: {self._session.session_id}")

        # ── Contextual tip ────────────────────────────────────────────
        from ember_code.utils.tips import get_tip

        tip = get_tip(self.settings, self._session.project_dir)
        with contextlib.suppress(NoMatches):
            self.query_one("#tip-bar", TipBar).set_tip(tip)

        self.query_one("#user-input", TextArea).focus()

        # ── Check for updates (non-blocking) ─────────────────────────
        asyncio.create_task(self._check_for_update())

        if self.initial_message:
            task = asyncio.create_task(
                self._execution.process_message(self.initial_message),
            )
            self._execution.current_task = task

    # ── Input events ──────────────────────────────────────────────

    @on(TextArea.Changed, "#user-input")
    def _on_input_changed(self, event: TextArea.Changed) -> None:
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
            area = self.query_one("#input-area", Vertical)
            area.mount(Static(f"[dim]{hint}[/dim]", id="autocomplete"))
        except Exception:
            pass

    async def on_key(self, event) -> None:
        input_widget = self.query_one("#user-input", TextArea)
        if not input_widget.has_focus:
            return

        if event.key == "up" and self._input_handler:
            entry = self._input_handler.on_up(input_widget.text)
            if entry is not None:
                event.prevent_default()
                input_widget.clear()
                input_widget.insert(entry)
                return

        if event.key == "down" and self._input_handler:
            entry = self._input_handler.on_down()
            if entry is not None:
                event.prevent_default()
                input_widget.clear()
                input_widget.insert(entry)
                return

        if event.key == "enter" and not event.shift:
            event.prevent_default()
            if self._input_handler:
                submitted = self._input_handler.on_submit(input_widget.text)
                if submitted:
                    input_widget.clear()
                    with contextlib.suppress(NoMatches):
                        self.query_one("#autocomplete", Static).display = False
                    task = asyncio.create_task(
                        self._execution.process_message(submitted),
                    )
                    if not self._execution.processing:
                        self._execution.current_task = task

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
        self.query_one("#user-input", TextArea).focus()

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
        input_widget = self.query_one("#user-input", TextArea)
        input_widget.clear()
        input_widget.insert(event.text)
        input_widget.focus()

    @on(QueuePanel.PanelClosed)
    def _on_queue_panel_closed(self, _event: QueuePanel.PanelClosed) -> None:
        with contextlib.suppress(NoMatches):
            self.query_one("#queue-panel", QueuePanel).add_class("-hidden")
        self.query_one("#user-input", TextArea).focus()

    # ── Actions (Textual keybindings) ─────────────────────────────

    def action_clear_screen(self) -> None:
        self._sessions.clear()

    def action_toggle_expand_all(self) -> None:
        container = self._conversation.container
        widgets = container.query(MessageWidget)
        any_collapsed = any(w._is_long and not w.expanded for w in widgets)
        for w in widgets:
            w.set_expanded(any_collapsed)
        state = "expanded" if any_collapsed else "collapsed"
        self._conversation.append_info(f"Messages {state}")

    def action_toggle_queue(self) -> None:
        """Toggle queue panel visibility and focus."""
        try:
            panel = self.query_one("#queue-panel", QueuePanel)
            if panel.has_class("-hidden") and self._execution.queue_size > 0:
                panel.remove_class("-hidden")
                panel.focus()
            else:
                panel.add_class("-hidden")
                self.query_one("#user-input", TextArea).focus()
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

    def action_cancel(self) -> None:
        self._execution.cancel()
