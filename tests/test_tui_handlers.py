"""Tests for TUI handler classes: StreamHandler, InputHandler, CommandHandler, ExecutionManager."""

import sys

import pytest

from ember_code.tui.command_handler import CommandHandler, CommandResult
from ember_code.tui.input_handler import (
    SHORTCUT_HELP,
    AutocompleteProvider,
    InputHandler,
    shortcut_label,
)
from ember_code.tui.stream_handler import StreamHandler, TokenMetrics

# ── TokenMetrics ──────────────────────────────────────────────────


class TestTokenMetrics:
    def test_initial_zero(self):
        m = TokenMetrics()
        assert m.input_tokens == 0
        assert m.output_tokens == 0
        assert m.total == 0

    def test_total(self):
        m = TokenMetrics()
        m.input_tokens = 100
        m.output_tokens = 50
        assert m.total == 150

    def test_accumulate_from_metrics_skips_if_already_populated(self):
        m = TokenMetrics()
        m.input_tokens = 100
        m.output_tokens = 50

        class FakeMetrics:
            input_tokens = 999
            output_tokens = 888

        m.accumulate_from_metrics(FakeMetrics())
        # Should NOT overwrite since input_tokens > 0
        assert m.input_tokens == 100
        assert m.output_tokens == 50

    def test_accumulate_from_metrics_populates_if_empty(self):
        m = TokenMetrics()

        class FakeMetrics:
            input_tokens = 200
            output_tokens = 100

        m.accumulate_from_metrics(FakeMetrics())
        assert m.input_tokens == 200
        assert m.output_tokens == 100


# ── StreamHandler._format_tool_args ──────────────────────────────


class TestFormatToolArgs:
    def test_none_args(self):
        assert StreamHandler._format_tool_args(None) == ""

    def test_empty_dict(self):
        assert StreamHandler._format_tool_args({}) == ""

    def test_simple_args(self):
        result = StreamHandler._format_tool_args({"path": "main.py", "line": 42})
        assert "path=main.py" in result
        assert "line=42" in result

    def test_long_value_truncated(self):
        result = StreamHandler._format_tool_args({"content": "a" * 50})
        assert "..." in result
        assert len(result) < 50

    def test_max_three_args(self):
        args = {f"key{i}": f"val{i}" for i in range(5)}
        result = StreamHandler._format_tool_args(args)
        # Should only have 3 key=val pairs
        assert result.count("=") == 3


# ── AutocompleteProvider ──────────────────────────────────────────


class TestAutocompleteProvider:
    def test_empty_input(self):
        p = AutocompleteProvider()
        assert p.complete("") == []

    def test_non_slash(self):
        p = AutocompleteProvider()
        assert p.complete("hello") == []

    def test_double_slash_ignored(self):
        p = AutocompleteProvider()
        assert p.complete("//comment") == []

    def test_partial_match(self):
        p = AutocompleteProvider()
        matches = p.complete("/he")
        assert "/help" in matches

    def test_exact_match_returns_empty(self):
        p = AutocompleteProvider()
        # If user typed exact command, no suggestions needed
        assert p.complete("/help") == []

    def test_multiple_matches(self):
        p = AutocompleteProvider()
        # /q matches /quit
        matches = p.complete("/q")
        assert "/quit" in matches

    def test_max_five_results(self):
        p = AutocompleteProvider()
        # Even if somehow many match, capped at 5
        matches = p.complete("/")
        assert len(matches) <= 5


# ── InputHandler ──────────────────────────────────────────────────


class TestInputHandler:
    def test_on_submit_returns_stripped(self):
        h = InputHandler()
        assert h.on_submit("  hello  ") == "hello"

    def test_on_submit_empty_returns_none(self):
        h = InputHandler()
        assert h.on_submit("") is None
        assert h.on_submit("   ") is None

    def test_on_submit_pushes_to_history(self):
        h = InputHandler()
        h.on_submit("first")
        h.on_submit("second")
        assert h.history.history == ["first", "second"]

    def test_on_up_down(self):
        h = InputHandler()
        h.on_submit("cmd1")
        h.on_submit("cmd2")
        assert h.on_up("") == "cmd2"
        assert h.on_up("") == "cmd1"
        assert h.on_down() == "cmd2"

    def test_get_completions(self):
        h = InputHandler()
        matches = h.get_completions("/he")
        assert "/help" in matches


# ── shortcut_label ────────────────────────────────────────────────


class TestShortcutLabel:
    def test_ctrl_on_macos(self):
        if sys.platform == "darwin":
            assert shortcut_label("Ctrl+D") == "⌃D"
        else:
            assert shortcut_label("Ctrl+D") == "Ctrl+D"

    def test_plain_key_unchanged(self):
        assert shortcut_label("Enter") == "Enter"

    def test_shortcut_help_contains_keys(self):
        assert "send message" in SHORTCUT_HELP
        assert "quit" in SHORTCUT_HELP
        assert "input history" in SHORTCUT_HELP


# ── CommandResult ─────────────────────────────────────────────────


class TestCommandResult:
    def test_markdown_result(self):
        r = CommandResult.markdown("## Hello")
        assert r.kind == "markdown"
        assert r.content == "## Hello"
        assert r.action is None

    def test_info_result(self):
        r = CommandResult.info("done")
        assert r.kind == "info"

    def test_error_result(self):
        r = CommandResult.error("oops")
        assert r.kind == "error"

    def test_quit_result(self):
        r = CommandResult.quit()
        assert r.action == "quit"

    def test_clear_result(self):
        r = CommandResult.clear()
        assert r.action == "clear"


# ── CommandHandler ────────────────────────────────────────────────


class TestCommandHandler:
    """Tests for CommandHandler using a minimal mock session."""

    @pytest.fixture
    def mock_session(self):
        class MockSkillPool:
            def list_skills(self):
                return []

            def match_user_command(self, cmd):
                return None

        class MockPool:
            def list_agents(self):
                return []

            @property
            def agent_names(self):
                return []

        class MockPermissions:
            file_write = "ask"
            shell_execute = "ask"

        class MockModels:
            default = "test-model"

        class MockOrchestration:
            max_total_agents = 10
            max_nesting_depth = 3

        class MockStorage:
            backend = "sqlite"

        class MockDisplay:
            show_routing = False

        class MockMemory:
            enable_agentic_memory = True
            add_memories_to_context = True

        class MockKnowledge:
            enabled = False
            embedder = "ember"

        class MockLearning:
            enabled = False

        class MockReasoning:
            enabled = False

        class MockGuardrails:
            pii_detection = False
            prompt_injection = False
            moderation = False

        class MockSettings:
            models = MockModels()
            permissions = MockPermissions()
            orchestration = MockOrchestration()
            storage = MockStorage()
            memory = MockMemory()
            knowledge = MockKnowledge()
            learning = MockLearning()
            reasoning = MockReasoning()
            guardrails = MockGuardrails()
            display = MockDisplay()

        class MockPersistence:
            async def rename(self, name):
                pass

        class MockMemoryMgr:
            async def get_memories(self):
                return []

            async def optimize(self):
                return {
                    "count_before": 0,
                    "count_after": 0,
                    "message": "Not enough memories to optimize",
                }

        class MockSession:
            skill_pool = MockSkillPool()
            pool = MockPool()
            settings = MockSettings()
            session_id = "test-123"
            hooks_map = {}
            persistence = MockPersistence()
            memory_mgr = MockMemoryMgr()

        return MockSession()

    @pytest.mark.asyncio
    async def test_quit(self, mock_session):
        handler = CommandHandler(mock_session)
        result = await handler.handle("/quit")
        assert result.action == "quit"

    @pytest.mark.asyncio
    async def test_exit(self, mock_session):
        handler = CommandHandler(mock_session)
        result = await handler.handle("/exit")
        assert result.action == "quit"

    @pytest.mark.asyncio
    async def test_help(self, mock_session):
        handler = CommandHandler(mock_session)
        result = await handler.handle("/help")
        assert result.kind == "markdown"
        assert "Commands" in result.content
        assert "Keyboard Shortcuts" in result.content

    @pytest.mark.asyncio
    async def test_agents(self, mock_session):
        handler = CommandHandler(mock_session)
        result = await handler.handle("/agents")
        assert result.kind == "markdown"
        assert "Agents" in result.content

    @pytest.mark.asyncio
    async def test_skills(self, mock_session):
        handler = CommandHandler(mock_session)
        result = await handler.handle("/skills")
        assert result.kind == "markdown"

    @pytest.mark.asyncio
    async def test_hooks_empty(self, mock_session):
        handler = CommandHandler(mock_session)
        result = await handler.handle("/hooks")
        assert result.kind == "info"
        assert "No hooks" in result.content

    @pytest.mark.asyncio
    async def test_clear(self, mock_session):
        handler = CommandHandler(mock_session)
        result = await handler.handle("/clear")
        assert result.action == "clear"

    @pytest.mark.asyncio
    async def test_config(self, mock_session):
        handler = CommandHandler(mock_session)
        result = await handler.handle("/config")
        assert result.kind == "markdown"
        assert "test-model" in result.content
        assert "Compression" in result.content

    @pytest.mark.asyncio
    async def test_sessions(self, mock_session):
        handler = CommandHandler(mock_session)
        result = await handler.handle("/sessions")
        assert result.action == "sessions"

    @pytest.mark.asyncio
    async def test_clear_rotates_session_id(self, mock_session):
        handler = CommandHandler(mock_session)
        old_id = mock_session.session_id
        await handler.handle("/clear")
        assert mock_session.session_id != old_id

    @pytest.mark.asyncio
    async def test_rename_no_args(self, mock_session):
        handler = CommandHandler(mock_session)
        result = await handler.handle("/rename")
        assert result.kind == "error"
        assert "Usage" in result.content

    @pytest.mark.asyncio
    async def test_rename_with_name(self, mock_session):
        handler = CommandHandler(mock_session)
        result = await handler.handle("/rename My Session")
        assert result.kind == "info"
        assert "My Session" in result.content

    @pytest.mark.asyncio
    async def test_memory_list_empty(self, mock_session):
        handler = CommandHandler(mock_session)
        result = await handler.handle("/memory")
        assert result.kind == "info"
        assert "No memories" in result.content

    @pytest.mark.asyncio
    async def test_memory_list_with_items(self, mock_session):
        async def mock_get():
            return [
                {"memory": "User prefers pytest", "topics": "testing"},
                {"memory": "User uses Python 3.13", "topics": "python"},
            ]

        mock_session.memory_mgr.get_memories = mock_get

        handler = CommandHandler(mock_session)
        result = await handler.handle("/memory")
        assert result.kind == "markdown"
        assert "pytest" in result.content
        assert "2" in result.content

    @pytest.mark.asyncio
    async def test_memory_optimize(self, mock_session):
        async def mock_optimize():
            return {"count_before": 5, "count_after": 1, "message": "Optimized 5 memories into 1"}

        mock_session.memory_mgr.optimize = mock_optimize

        handler = CommandHandler(mock_session)
        result = await handler.handle("/memory optimize")
        assert result.kind == "info"
        assert "Optimized" in result.content

    @pytest.mark.asyncio
    async def test_memory_optimize_error(self, mock_session):
        async def mock_optimize():
            return {"error": "No db"}

        mock_session.memory_mgr.optimize = mock_optimize

        handler = CommandHandler(mock_session)
        result = await handler.handle("/memory optimize")
        assert result.kind == "error"

    @pytest.mark.asyncio
    async def test_unknown_command(self, mock_session):
        handler = CommandHandler(mock_session)
        result = await handler.handle("/nonexistent")
        assert result.kind == "error"
        assert "Unknown" in result.content


# ── ExecutionManager queue ───────────────────────────────────────


class TestExecutionManagerQueue:
    """Tests for the message queue in ExecutionManager."""

    def _make_em(self):
        from ember_code.tui.execution_manager import ExecutionManager

        em = ExecutionManager.__new__(ExecutionManager)
        em._queue = []
        em._app = None  # _sync_queue_panel will silently fail
        return em

    def test_enqueue_returns_position(self):
        em = self._make_em()
        assert em.enqueue("first") == 1
        assert em.enqueue("second") == 2
        assert em.queue_size == 2

    def test_enqueue_no_limit(self):
        em = self._make_em()
        for i in range(100):
            em.enqueue(f"msg-{i}")
        assert em.queue_size == 100

    def test_dequeue_at(self):
        em = self._make_em()
        em.enqueue("a")
        em.enqueue("b")
        em.enqueue("c")
        removed = em.dequeue_at(1)
        assert removed == "b"
        assert em.queue_size == 2
        assert em._queue == ["a", "c"]

    def test_dequeue_at_invalid(self):
        em = self._make_em()
        em.enqueue("a")
        assert em.dequeue_at(5) is None
        assert em.dequeue_at(-1) is None
        assert em.queue_size == 1

    def test_edit_at(self):
        em = self._make_em()
        em.enqueue("old message")
        assert em.edit_at(0, "new message") is True
        assert em._queue[0] == "new message"

    def test_edit_at_invalid(self):
        em = self._make_em()
        assert em.edit_at(0, "text") is False

    def test_clear_queue(self):
        em = self._make_em()
        em.enqueue("a")
        em.enqueue("b")
        em.clear_queue()
        assert em.queue_size == 0

    def test_queue_size_property(self):
        em = self._make_em()
        assert em.queue_size == 0
        em._queue.append("x")
        assert em.queue_size == 1


# ── QueueInjectorHook ────────────────────────────────────────────


class TestQueueInjectorHook:
    """Tests for the tool hook that injects queued messages mid-run."""

    def _make_hook(self, queue=None, on_inject=None, on_queue_changed=None):
        from ember_code.tui.queue_hook import QueueInjectorHook

        return QueueInjectorHook(
            queue=queue if queue is not None else [],
            on_inject=on_inject,
            on_queue_changed=on_queue_changed,
        )

    @pytest.mark.asyncio
    async def test_calls_next_func_and_returns_result(self):
        hook = self._make_hook()

        async def next_func(**kwargs):
            return "tool_result"

        result = await hook("my_tool", None, {}, next_func)
        assert result == "tool_result"

    @pytest.mark.asyncio
    async def test_calls_sync_next_func(self):
        hook = self._make_hook()

        def next_func(**kwargs):
            return "sync_result"

        result = await hook("my_tool", None, {}, next_func)
        assert result == "sync_result"

    @pytest.mark.asyncio
    async def test_injects_queued_messages(self):
        queue = ["hello from user"]

        class FakeAgent:
            additional_input = None

        agent = FakeAgent()
        hook = self._make_hook(queue=queue)

        async def next_func(**kwargs):
            return "ok"

        await hook("tool", None, {}, next_func, agent=agent)

        assert agent.additional_input is not None
        assert len(agent.additional_input) == 1
        assert "hello from user" in agent.additional_input[0].content
        assert queue == []  # drained

    @pytest.mark.asyncio
    async def test_clears_previous_injection_on_next_call(self):
        queue = ["msg1"]

        class FakeAgent:
            additional_input = None

        agent = FakeAgent()
        hook = self._make_hook(queue=queue)

        async def next_func(**kwargs):
            return "ok"

        # First call: injects msg1
        await hook("tool", None, {}, next_func, agent=agent)
        assert agent.additional_input is not None

        # Second call (no new messages): clears previous injection
        await hook("tool", None, {}, next_func, agent=agent)
        assert agent.additional_input is None

    @pytest.mark.asyncio
    async def test_on_inject_callback(self):
        injected = []
        queue = ["a", "b"]
        hook = self._make_hook(queue=queue, on_inject=lambda msg: injected.append(msg))

        class FakeAgent:
            additional_input = None

        async def next_func(**kwargs):
            return "ok"

        await hook("tool", None, {}, next_func, agent=FakeAgent())
        assert injected == ["a", "b"]

    @pytest.mark.asyncio
    async def test_on_queue_changed_callback(self):
        changed_count = []
        queue = ["x"]
        hook = self._make_hook(
            queue=queue,
            on_queue_changed=lambda: changed_count.append(1),
        )

        class FakeAgent:
            additional_input = None

        async def next_func(**kwargs):
            return "ok"

        await hook("tool", None, {}, next_func, agent=FakeAgent())
        assert len(changed_count) == 1

    @pytest.mark.asyncio
    async def test_no_agent_skips_injection(self):
        queue = ["msg"]
        hook = self._make_hook(queue=queue)

        async def next_func(**kwargs):
            return "ok"

        result = await hook("tool", None, {}, next_func, agent=None)
        assert result == "ok"
        assert queue == ["msg"]  # not drained without agent

    def test_reset(self):
        hook = self._make_hook()
        hook._has_injected = True
        hook.reset()
        assert hook._has_injected is False

    def test_create_queue_hook_factory(self):
        from ember_code.tui.queue_hook import create_queue_hook

        queue = []
        hook = create_queue_hook(queue)
        assert hook._queue is queue
