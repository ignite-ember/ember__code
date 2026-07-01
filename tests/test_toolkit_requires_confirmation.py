"""Regression: async tools in a Toolkit must get
``requires_confirmation`` set from ``requires_confirmation_tools``.

The bug this file guards: ``EmberShellTools.__init__`` (and
``EmberEditTools.__init__``) accepted a
``requires_confirmation_tools`` kwarg, then post-registration
looped over ``self.functions`` to flip
``func.requires_confirmation = True``. Agno's
``Toolkit.register`` routes async callables (``run_shell_command``
is async) into ``self.async_functions``, not ``self.functions``,
so the flip missed them.

Consequence in prod: fresh v0.8.0 installs never saw the HITL
approval dialog before ``run_shell_command`` fired — Agno never
paused, the tool went straight to execution, and ``tool_hook``
returned the "no canUseTool bridge is wired yet" string that the
agent then narrated back at the user. The user's terminal chat
looked like: type "start a server" → agent tries → gets blocked
string → gives up. No dialog, no way to approve.

The fix iterates BOTH registries. This test locks that in.
"""

from __future__ import annotations

from ember_code.core.tools.edit import EmberEditTools
from ember_code.core.tools.shell import EmberShellTools


class TestShellToolkitConfirmation:
    def test_run_shell_command_has_requires_confirmation_flag(self) -> None:
        # ``run_shell_command`` is async — used to be routed to
        # ``async_functions`` and skipped by the confirm-loop.
        toolkit = EmberShellTools(requires_confirmation_tools=["run_shell_command"])
        # Find the tool wherever it landed (sync or async
        # registry — both are valid Agno storage).
        by_name: dict[str, object] = {}
        by_name.update(toolkit.functions)
        by_name.update(toolkit.async_functions)
        func = by_name["run_shell_command"]
        assert getattr(func, "requires_confirmation", False) is True, (
            "run_shell_command's Function object must have "
            "requires_confirmation=True after toolkit construction. "
            "If this fails, Agno won't pause the run, no HITL "
            "dialog fires, and the model gets the raw ``tool_hook`` "
            "block string. See the v0.8.0 upgrade regression."
        )

    def test_stop_process_also_flagged(self) -> None:
        # ``stop_process`` is listed in the toolkit's confirm set
        # from ``registry.py::_make_bash``; ensure the same fix
        # covers it (also async, would have hit the same bug).
        toolkit = EmberShellTools(requires_confirmation_tools=["run_shell_command", "stop_process"])
        by_name: dict[str, object] = {}
        by_name.update(toolkit.functions)
        by_name.update(toolkit.async_functions)
        assert getattr(by_name["stop_process"], "requires_confirmation", False) is True

    def test_unlisted_async_tool_not_flagged(self) -> None:
        # Sanity: tools not in the confirm list stay
        # unconfirmed. The bug fix must not accidentally flag
        # EVERY async tool.
        toolkit = EmberShellTools(requires_confirmation_tools=["run_shell_command"])
        by_name: dict[str, object] = {}
        by_name.update(toolkit.functions)
        by_name.update(toolkit.async_functions)
        # ``list_processes`` is async but NOT in the confirm
        # list — should be False.
        list_proc = by_name.get("list_processes")
        if list_proc is not None:
            assert getattr(list_proc, "requires_confirmation", False) is False


class TestEditToolkitConfirmation:
    def test_edit_file_has_requires_confirmation_flag(self) -> None:
        # ``edit_file`` / ``create_file`` / ``edit_file_replace_all``
        # are all async in ``EmberEditTools`` — same async-registry
        # bug applied to file edits.
        toolkit = EmberEditTools(
            requires_confirmation_tools=[
                "edit_file",
                "create_file",
                "edit_file_replace_all",
            ]
        )
        by_name: dict[str, object] = {}
        by_name.update(toolkit.functions)
        by_name.update(toolkit.async_functions)
        for tool_name in ("edit_file", "create_file", "edit_file_replace_all"):
            func = by_name.get(tool_name)
            assert func is not None, f"missing {tool_name} in toolkit"
            assert getattr(func, "requires_confirmation", False) is True, (
                f"{tool_name} must have requires_confirmation=True; "
                "async-registry mutation regression."
            )
