"""HITLHandler — handles Human-in-the-Loop requirements."""

from typing import TYPE_CHECKING, Any

from ember_code.tui.widgets import PermissionDialog

if TYPE_CHECKING:
    from ember_code.tui.app import EmberApp
    from ember_code.tui.conversation_view import ConversationView


class HITLHandler:
    """Handles Human-in-the-Loop requirements: confirmations and user input."""

    def __init__(self, app: "EmberApp", conversation: "ConversationView"):
        self._app = app
        self._conversation = conversation

    async def handle(self, executor: Any, run_response: Any) -> None:
        for requirement in run_response.active_requirements:
            if requirement.needs_confirmation:
                await self._handle_confirmation(requirement)
            elif requirement.needs_user_input:
                self._handle_user_input(requirement)

        # Continue the run after all requirements are resolved
        try:
            if hasattr(executor, "acontinue_run"):
                continued = await executor.acontinue_run(
                    run_response=run_response,
                )
                if hasattr(continued, "content"):
                    self._conversation.append_assistant(str(continued.content))
        except Exception as e:
            self._conversation.append_error(f"HITL continue error: {e}")

    async def _handle_confirmation(self, requirement: Any) -> None:
        tool_name = ""
        tool_args = ""
        if requirement.tool_execution:
            tool_name = requirement.tool_execution.tool_name or ""
            tool_args = str(requirement.tool_execution.tool_args or "")

        self._conversation.append_info(f"Agent wants to call: {tool_name}({tool_args[:100]})")

        dialog = PermissionDialog(
            tool_name=tool_name,
            details=tool_args[:200],
        )
        await self._app.mount(dialog)
        dialog.focus()

        approved = await dialog.wait_for_decision()
        if approved:
            requirement.confirm()
        else:
            requirement.reject("User denied via TUI")

    def _handle_user_input(self, requirement: Any) -> None:
        self._conversation.append_info("Agent is requesting additional input.")
        # For now, provide empty input — future: show input dialog
        requirement.provide_user_input({})
