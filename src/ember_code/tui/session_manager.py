"""SessionManager — manages session lifecycle: picking, switching, clearing."""

from typing import TYPE_CHECKING

from ember_code.tui.widgets import PromptInput, SessionInfo, SessionPickerWidget

if TYPE_CHECKING:
    from ember_code.session import Session
    from ember_code.tui.app import EmberApp
    from ember_code.tui.conversation_view import ConversationView
    from ember_code.tui.status_tracker import StatusTracker


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

    @property
    def _session(self) -> "Session":
        return self._app.session

    def clear(self) -> None:
        self._conversation.clear()
        self._status.message_count = 0

    async def show_picker(self) -> None:
        raw_sessions = await self._session.persistence.list_sessions(limit=20)
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
            for s in raw_sessions
        ]
        picker = SessionPickerWidget(
            infos,
            current_session_id=self._session.session_id,
        )
        self._app.mount(picker)
        picker.focus()

    async def switch_to(self, session_id: str) -> None:
        self._session.session_id = session_id
        self._session.session_named = True
        # Update the agent and persistence so Agno loads the correct history
        self._session.main_team.session_id = session_id
        self._session.persistence.session_id = session_id
        self.clear()
        self._status.reset()
        name = await self._session.persistence.get_name()
        label = f"{name} ({session_id})" if name else session_id
        self._conversation.append_info(f"Resumed session: {label}")

        # Load and display previous messages
        await self._load_history(session_id)

        self._status.update_status_bar()
        self._app.query_one("#user-input", PromptInput).focus()

    async def _load_history(self, session_id: str) -> None:
        """Load chat history from the DB and render in the conversation view."""
        try:
            agent = self._session.main_team
            agno_session = await agent.aget_session(
                session_id=session_id,
                user_id=self._session.user_id,
            )
            if agno_session is None:
                return

            messages = agno_session.get_chat_history()
            if not messages:
                self._conversation.append_info("(no previous messages)")
                return

            for msg in messages:
                content = msg.content if isinstance(msg.content, str) else str(msg.content or "")
                if not content.strip():
                    continue
                # Strip think tags from assistant messages
                if msg.role == "assistant":
                    import re

                    content = re.sub(r"<think>.*?</think>\s*", "", content, flags=re.DOTALL).strip()
                    if content:
                        self._conversation.append_assistant(content, expanded=True)
                elif msg.role == "user":
                    # Strip system-context tags injected at send time
                    import re

                    content = re.sub(
                        r"<system-context>.*?</system-context>\s*", "", content, flags=re.DOTALL
                    ).strip()
                    if content:
                        self._conversation.append_user(content, expanded=True)
        except Exception as e:
            import logging

            logging.getLogger(__name__).debug("Failed to load session history: %s", e)
