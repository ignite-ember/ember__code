"""Tests for hooks — events, loader, executor."""

import json

import pytest

from ember_code.hooks.events import HookEvent
from ember_code.hooks.executor import HookExecutor
from ember_code.hooks.loader import HookLoader, load_hooks
from ember_code.hooks.schemas import HookDefinition, HookResult


class TestHookEvent:
    def test_all_events_defined(self):
        expected = {
            "PreToolUse",
            "PostToolUse",
            "PostToolUseFailure",
            "UserPromptSubmit",
            "SessionStart",
            "SessionEnd",
            "Stop",
            "SubagentStart",
            "SubagentStop",
            "Notification",
        }
        actual = {e.value for e in HookEvent}
        assert actual == expected

    def test_event_values_are_strings(self):
        for event in HookEvent:
            assert isinstance(event.value, str)


class TestHookLoader:
    def test_load_empty(self, tmp_path):
        loader = HookLoader(tmp_path)
        hooks = loader.load()
        assert hooks == {}

    def test_load_from_project_settings(self, tmp_path):
        ember_dir = tmp_path / ".ember"
        ember_dir.mkdir()
        settings = ember_dir / "settings.json"
        settings.write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {"type": "command", "command": "echo check", "matcher": "Write|Edit"}
                        ]
                    }
                }
            )
        )

        loader = HookLoader(tmp_path)
        hooks = loader.load()
        assert "PreToolUse" in hooks
        assert len(hooks["PreToolUse"]) == 1
        assert hooks["PreToolUse"][0].command == "echo check"
        assert hooks["PreToolUse"][0].matcher == "Write|Edit"

    def test_load_multiple_events(self, tmp_path):
        ember_dir = tmp_path / ".ember"
        ember_dir.mkdir()
        settings = ember_dir / "settings.json"
        settings.write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [{"type": "command", "command": "echo pre"}],
                        "PostToolUse": [{"type": "command", "command": "echo post"}],
                        "Stop": [{"type": "http", "url": "https://example.com/hook"}],
                    }
                }
            )
        )

        loader = HookLoader(tmp_path)
        hooks = loader.load()
        assert len(hooks) == 3
        assert hooks["Stop"][0].type == "http"
        assert hooks["Stop"][0].url == "https://example.com/hook"

    def test_load_hooks_convenience(self, tmp_path):
        hooks = load_hooks(tmp_path)
        assert hooks == {}

    def test_hook_definition_defaults(self):
        h = HookDefinition(type="command", command="echo test")
        assert h.timeout == 10000
        assert h.matcher == ""
        assert h.headers == {}
        assert h.url == ""

    def test_ignores_invalid_json(self, tmp_path):
        ember_dir = tmp_path / ".ember"
        ember_dir.mkdir()
        (ember_dir / "settings.json").write_text("not json {{{")

        loader = HookLoader(tmp_path)
        hooks = loader.load()
        assert hooks == {}

    def test_ignores_non_list_hooks(self, tmp_path):
        ember_dir = tmp_path / ".ember"
        ember_dir.mkdir()
        (ember_dir / "settings.json").write_text(
            json.dumps({"hooks": {"PreToolUse": "not a list"}})
        )

        loader = HookLoader(tmp_path)
        hooks = loader.load()
        assert hooks == {}


class TestHookExecutor:
    def test_no_hooks_returns_continue(self):
        executor = HookExecutor({})
        import asyncio

        result = asyncio.get_event_loop().run_until_complete(
            executor.execute("PreToolUse", {"tool": "Read"})
        )
        assert result.should_continue is True

    def test_get_matching_hooks_no_matcher(self):
        hook = HookDefinition(type="command", command="echo test")
        executor = HookExecutor({"PreToolUse": [hook]})
        matches = executor.get_matching_hooks("PreToolUse", "Write")
        assert len(matches) == 1

    def test_get_matching_hooks_with_matcher(self):
        hook = HookDefinition(type="command", command="echo test", matcher="Write|Edit")
        executor = HookExecutor({"PreToolUse": [hook]})

        assert len(executor.get_matching_hooks("PreToolUse", "Write")) == 1
        assert len(executor.get_matching_hooks("PreToolUse", "Read")) == 0

    def test_get_matching_hooks_no_event(self):
        executor = HookExecutor({})
        assert executor.get_matching_hooks("PreToolUse", "Write") == []

    @pytest.mark.asyncio
    async def test_execute_command_hook_success(self, tmp_path):
        hook = HookDefinition(
            type="command",
            command="echo '{\"continue\": true}'",
            timeout=5000,
        )
        executor = HookExecutor({"PreToolUse": [hook]})
        result = await executor.execute("PreToolUse", {"tool": "Read"})
        assert result.should_continue is True

    @pytest.mark.asyncio
    async def test_execute_no_matching_event(self):
        hook = HookDefinition(type="command", command="echo test")
        executor = HookExecutor({"Stop": [hook]})
        result = await executor.execute("PreToolUse", {"tool": "Read"})
        assert result.should_continue is True

    def test_hook_result_defaults(self):
        r = HookResult()
        assert r.should_continue is True
        assert r.message == ""
