"""SessionManager — manages session lifecycle: picking, switching, clearing."""

from typing import TYPE_CHECKING

from ember_code.frontend.tui.widgets import PromptInput, SessionInfo, SessionPickerWidget

if TYPE_CHECKING:
    from ember_code.frontend.tui.app import EmberApp
    from ember_code.frontend.tui.conversation_view import ConversationView
    from ember_code.frontend.tui.status_tracker import StatusTracker


class SessionManager:
    """Manages session lifecycle: picking, switching, renaming, clearing."""

    def __init__(
        self,
        app: "EmberApp",
        conversation: "ConversationView",
        status: "StatusTracker",
    ):
        self._app = app
        self._conversation = conversation
        self._status = status

    def clear(self) -> None:
        self._conversation.clear()
        self._status.message_count = 0

    async def show_picker(self) -> None:
        result = await self._app.backend.list_sessions()
        infos = [
            SessionInfo(
                session_id=s["session_id"],
                name=s["name"],
                created_at=s["created_at"],
                updated_at=s["updated_at"],
                run_count=s["run_count"],
                summary=s["summary"],
                agent_name=s["agent_name"],
            )
            for s in result.sessions
        ]
        picker = SessionPickerWidget(
            infos,
            current_session_id=self._app.backend.session_id,
        )
        self._app.mount(picker)
        picker.focus()

    async def switch_to(self, session_id: str) -> None:
        result = await self._app.backend.switch_session(session_id)
        self.clear()
        self._status.reset()
        self._conversation.append_info(result.text)

        # Load and display previous messages
        await self._load_history(session_id)

        self._status.update_status_bar()
        self._app.query_one("#user-input", PromptInput).focus()

    async def _load_history(self, session_id: str) -> None:
        """Load chat history from the backend and render in the conversation view."""
        import re

        try:
            messages = await self._app.backend.get_chat_history(session_id)
            if not messages:
                self._conversation.append_info("(no previous messages)")
                return

            for msg in messages:
                content = msg.get("content", "")
                if not content.strip():
                    continue
                if msg.get("role") == "assistant":
                    content = re.sub(r"<think>.*?</think>\s*", "", content, flags=re.DOTALL).strip()
                    if content:
                        self._conversation.append_assistant(content, expanded=True)
                elif msg.get("role") == "user":
                    content = re.sub(
                        r"<system-context>.*?</system-context>\s*", "", content, flags=re.DOTALL
                    ).strip()
                    if content:
                        self._conversation.append_user(content, expanded=True)
        except Exception as e:
            import logging

            logging.getLogger(__name__).debug("Failed to load session history: %s", e)
