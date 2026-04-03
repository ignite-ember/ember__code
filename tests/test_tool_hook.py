"""Tests for tool event hooks — PreToolUse/PostToolUse/PostToolUseFailure."""

import json
import tempfile
from pathlib import Path

import pytest

from ember_code.hooks.executor import HookExecutor
from ember_code.hooks.schemas import HookDefinition
from ember_code.hooks.tool_hook import ToolEventHook, _preview, _safe_args


class TestToolEventHookPassthrough:
    """When no hooks are configured, tools run normally."""

    def test_no_hooks_passes_through(self):
        executor = HookExecutor({})
        hook = ToolEventHook(executor, session_id="test")

        result = hook(
            name="read_file", func=lambda path="x": f"content of {path}", args={"path": "foo.py"}
        )
        assert result == "content of foo.py"

    def test_no_hooks_propagates_exception(self):
        executor = HookExecutor({})
        hook = ToolEventHook(executor, session_id="test")

        def exploding():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            hook(name="bad_tool", func=exploding, args={})

    def test_none_func_returns_none(self):
        executor = HookExecutor({})
        hook = ToolEventHook(executor, session_id="test")

        result = hook(name="noop", func=None, args={})
        assert result is None

    def test_none_args_defaults_to_empty(self):
        executor = HookExecutor({})
        hook = ToolEventHook(executor, session_id="test")

        called_with = {}

        def capture(**kwargs):
            called_with.update(kwargs)
            return "ok"

        hook(name="test", func=capture, args=None)
        assert called_with == {}


class TestPreToolUse:
    """PreToolUse hooks can block tool execution."""

    def test_blocks_tool_with_exit_2(self):
        hooks = {"PreToolUse": [HookDefinition(type="command", command="exit 2")]}
        hook = ToolEventHook(HookExecutor(hooks), session_id="test")

        called = []

        def tracked():
            called.append(True)
            return "ran"

        result = hook(name="some_tool", func=tracked, args={})
        assert "Blocked" in str(result)
        assert called == []  # func should NOT have been called

    def test_non_matching_tool_passes_through(self):
        hooks = {
            "PreToolUse": [HookDefinition(type="command", command="exit 2", matcher="dangerous")]
        }
        hook = ToolEventHook(HookExecutor(hooks), session_id="test")

        result = hook(name="safe_tool", func=lambda: "ok", args={})
        assert result == "ok"


class TestPostToolUse:
    """PostToolUse hooks fire after successful tool execution."""

    def test_fires_for_matching_tool(self):
        outfile = Path(tempfile.mktemp(suffix=".json"))
        hooks = {
            "PostToolUse": [
                HookDefinition(
                    type="command",
                    command=f"cat > {outfile}",
                    matcher="edit",
                )
            ]
        }
        hook = ToolEventHook(HookExecutor(hooks), session_id="s1")

        result = hook(name="edit_file", func=lambda: "edited", args={})
        assert result == "edited"

        # Hook should have written a JSON payload
        assert outfile.exists()
        data = json.loads(outfile.read_text())
        assert data["tool_name"] == "edit_file"
        assert data["session_id"] == "s1"
        outfile.unlink()

    def test_does_not_fire_for_non_matching_tool(self):
        outfile = Path(tempfile.mktemp(suffix=".json"))
        hooks = {
            "PostToolUse": [
                HookDefinition(
                    type="command",
                    command=f"cat > {outfile}",
                    matcher="Write|Edit",
                )
            ]
        }
        hook = ToolEventHook(HookExecutor(hooks), session_id="s1")

        hook(name="read_file", func=lambda: "content", args={})
        assert not outfile.exists()

    def test_does_not_fire_on_error(self):
        outfile = Path(tempfile.mktemp(suffix=".json"))
        hooks = {"PostToolUse": [HookDefinition(type="command", command=f"cat > {outfile}")]}
        hook = ToolEventHook(HookExecutor(hooks), session_id="s1")

        with pytest.raises(RuntimeError):
            hook(
                name="fail_tool", func=lambda: (_ for _ in ()).throw(RuntimeError("oops")), args={}
            )

        assert not outfile.exists()


class TestPostToolUseFailure:
    """PostToolUseFailure hooks fire after tool errors."""

    def test_fires_on_error(self):
        outfile = Path(tempfile.mktemp(suffix=".json"))
        hooks = {"PostToolUseFailure": [HookDefinition(type="command", command=f"cat > {outfile}")]}
        hook = ToolEventHook(HookExecutor(hooks), session_id="s1")

        def failing():
            raise RuntimeError("disk full")

        with pytest.raises(RuntimeError, match="disk full"):
            hook(name="save_file", func=failing, args={})

        assert outfile.exists()
        data = json.loads(outfile.read_text())
        assert data["tool_name"] == "save_file"
        assert "disk full" in data["error"]
        outfile.unlink()

    def test_does_not_fire_on_success(self):
        outfile = Path(tempfile.mktemp(suffix=".json"))
        hooks = {"PostToolUseFailure": [HookDefinition(type="command", command=f"cat > {outfile}")]}
        hook = ToolEventHook(HookExecutor(hooks), session_id="s1")

        hook(name="good_tool", func=lambda: "ok", args={})
        assert not outfile.exists()


class TestHookDetection:
    """ToolEventHook caches which events have hooks."""

    def test_detects_pre_hooks(self):
        hooks = {"PreToolUse": [HookDefinition(type="command", command="true")]}
        hook = ToolEventHook(HookExecutor(hooks))
        assert hook._has_pre is True
        assert hook._has_post is False
        assert hook._has_fail is False

    def test_detects_post_hooks(self):
        hooks = {"PostToolUse": [HookDefinition(type="command", command="true")]}
        hook = ToolEventHook(HookExecutor(hooks))
        assert hook._has_pre is False
        assert hook._has_post is True

    def test_detects_failure_hooks(self):
        hooks = {"PostToolUseFailure": [HookDefinition(type="command", command="true")]}
        hook = ToolEventHook(HookExecutor(hooks))
        assert hook._has_fail is True

    def test_no_hooks_detected(self):
        hook = ToolEventHook(HookExecutor({}))
        assert hook._has_pre is False
        assert hook._has_post is False
        assert hook._has_fail is False


class TestHelpers:
    def test_safe_args_truncates(self):
        args = {"big": "x" * 1000, "small": "hello"}
        safe = _safe_args(args)
        assert len(safe["big"]) == 500
        assert safe["small"] == "hello"

    def test_preview_none(self):
        assert _preview(None) == ""

    def test_preview_truncates(self):
        assert len(_preview("x" * 1000)) == 500

    def test_preview_short(self):
        assert _preview("ok") == "ok"
