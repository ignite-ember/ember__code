"""SessionManager — manages session lifecycle: picking, switching, clearing."""

from typing import TYPE_CHECKING

from textual.widgets import TextArea

from ember_code.tui.widgets import SessionInfo, SessionPickerWidget

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
        return self._app._session

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
        self.clear()
        self._status.reset()
        name = await self._session.persistence.get_name()
        label = f"{name} ({session_id})" if name else session_id
        self._conversation.append_info(f"Switched to session: {label}")
        self._status.update_status_bar()
        self._app.query_one("#user-input", TextArea).focus()
