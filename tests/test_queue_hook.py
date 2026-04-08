"""Tests for queue_hook.py — message queue injection during agent execution."""

from unittest.mock import MagicMock, patch

import pytest

from ember_code.queue_hook import QueueInjectorHook, create_queue_hook


class TestQueueInjectorHook:
    @pytest.mark.asyncio
    async def test_passes_through_func_result(self):
        hook = QueueInjectorHook(queue=[])
        result = await hook(name="test", func=lambda: "hello", args={})
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_passes_args_to_func(self):
        hook = QueueInjectorHook(queue=[])
        result = await hook(name="add", func=lambda x, y: x + y, args={"x": 1, "y": 2})
        assert result == 3

    @pytest.mark.asyncio
    async def test_no_func_returns_none(self):
        hook = QueueInjectorHook(queue=[])
        result = await hook(name="test")
        assert result is None

    @pytest.mark.asyncio
    async def test_injects_queued_messages(self):
        queue = ["message 1", "message 2"]
        agent = MagicMock()
        agent.additional_input = None

        hook = QueueInjectorHook(queue=queue)
        with patch("agno.models.message.Message") as MockMessage:
            MockMessage.side_effect = lambda **kw: MagicMock(**kw)
            await hook(name="tool", func=lambda: "ok", args={}, agent=agent)

        assert agent.additional_input is not None
        assert len(agent.additional_input) == 2
        assert queue == []

    @pytest.mark.asyncio
    async def test_clears_previous_injection(self):
        agent = MagicMock()
        agent.additional_input = "old stuff"

        hook = QueueInjectorHook(queue=[])
        hook._has_injected = True

        await hook(name="tool", func=lambda: "ok", args={}, agent=agent)
        assert agent.additional_input is None

    @pytest.mark.asyncio
    async def test_calls_on_inject_callback(self):
        on_inject = MagicMock()
        queue = ["hello"]
        agent = MagicMock()

        hook = QueueInjectorHook(queue=queue, on_inject=on_inject)
        with patch("agno.models.message.Message", MagicMock()):
            await hook(name="tool", func=lambda: None, args={}, agent=agent)

        on_inject.assert_called_once_with("hello")

    @pytest.mark.asyncio
    async def test_calls_on_queue_changed_callback(self):
        on_changed = MagicMock()
        queue = ["msg"]
        agent = MagicMock()

        hook = QueueInjectorHook(queue=queue, on_queue_changed=on_changed)
        with patch("agno.models.message.Message", MagicMock()):
            await hook(name="tool", func=lambda: None, args={}, agent=agent)

        on_changed.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_injection_when_queue_empty(self):
        agent = MagicMock(spec=["additional_input"])
        agent.additional_input = None
        hook = QueueInjectorHook(queue=[])
        await hook(name="tool", func=lambda: "ok", args={}, agent=agent)
        assert agent.additional_input is None

    def test_reset_clears_state(self):
        hook = QueueInjectorHook(queue=[])
        hook._has_injected = True
        hook.reset()
        assert hook._has_injected is False

    @pytest.mark.asyncio
    async def test_awaits_async_func(self):
        hook = QueueInjectorHook(queue=[])

        async def async_func():
            return "async ok"

        result = await hook(name="test", func=async_func, args={})
        assert result == "async ok"


class TestCreateQueueHook:
    def test_returns_hook_instance(self):
        hook = create_queue_hook([])
        assert isinstance(hook, QueueInjectorHook)

    def test_passes_callbacks(self):
        on_inject = MagicMock()
        on_changed = MagicMock()
        hook = create_queue_hook([], on_inject=on_inject, on_queue_changed=on_changed)
        assert hook._on_inject is on_inject
        assert hook._on_queue_changed is on_changed
