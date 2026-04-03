"""Tests for session/core.py — Session construction and message handling."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ember_code.config.settings import Settings


def _session_patches(**overrides):
    """Return a list of patch objects for all Session dependencies.

    *overrides* lets callers change specific return_values, e.g.
    ``_session_patches(get_access_token="tok-123")``.
    """
    defaults = {
        "initialize_project": None,
        "setup_db": None,
        "KnowledgeManager": None,
        "PermissionGuard": None,
        "AuditLogger": None,
        "HookLoader": None,
        "HookExecutor": None,
        "load_project_context": "",
        "AgentPool": None,
        "SkillPool": None,
        "ModelRegistry": None,
        "MCPClientManager": None,
        "SessionPersistence": None,
        "SessionMemoryManager": None,
        "SessionKnowledgeManager": None,
        "get_access_token": None,
        "get_org_id": None,
        "get_org_name": None,
        "ToolRegistry": None,
        "ToolPermissions": None,
        "create_learning_machine": None,
        "ToolEventHook": None,
        "_create_reasoning_tools": None,
        "_create_guardrails": None,
        "CompressionManager": None,
        "Team": None,
        "load_prompt": "You are an assistant.",
    }
    defaults.update(overrides)

    patches = []
    for name, rv in defaults.items():
        target = f"ember_code.session.core.{name}"
        # For classes (uppercase first letter), don't set return_value so
        # the mock acts as a callable that returns a fresh MagicMock.
        if name[0].isupper():
            p = patch(target)
            patches.append(p)
        else:
            patches.append(patch(target, return_value=rv))

    return patches


def _start_patches(patches):
    mocks = {}
    for p in patches:
        mock = p.start()
        mocks[p.attribute] = mock
    # ModelRegistry().get_context_window() must return an int for min()
    if "ModelRegistry" in mocks:
        mocks["ModelRegistry"].return_value.get_context_window.return_value = 128_000
    return list(mocks.values())


def _stop_patches(patches):
    for p in patches:
        p.stop()


class TestSessionConstruction:
    """Test Session initialization without hitting Agno or the network."""

    @pytest.fixture
    def _patch_deps(self, tmp_path):
        patches = _session_patches()
        _start_patches(patches)
        yield
        _stop_patches(patches)

    def test_creates_session_with_defaults(self, tmp_path, _patch_deps):
        from ember_code.session.core import Session

        settings = Settings()
        session = Session(settings, project_dir=tmp_path)

        assert session.project_dir == tmp_path
        assert session.session_id is not None
        assert len(session.session_id) == 8
        assert session.settings is settings

    def test_creates_session_with_resume_id(self, tmp_path, _patch_deps):
        from ember_code.session.core import Session

        session = Session(Settings(), project_dir=tmp_path, resume_session_id="my-session")
        assert session.session_id == "my-session"
        assert session.session_named is True

    def test_creates_session_with_additional_dirs(self, tmp_path, _patch_deps):
        from ember_code.session.core import Session

        extra = tmp_path / "extra"
        extra.mkdir()
        session = Session(Settings(), project_dir=tmp_path, additional_dirs=[extra])
        assert session.workspace.is_multi
        assert extra.resolve() in session.workspace.all_dirs

    def test_cloud_connected_false_by_default(self, tmp_path, _patch_deps):
        from ember_code.session.core import Session

        session = Session(Settings(), project_dir=tmp_path)
        assert session.cloud_connected is False
        assert session.cloud_org_id is None
        assert session.cloud_org_name is None

    def test_cloud_connected_true_with_token(self, tmp_path):
        patches = _session_patches(
            get_access_token="tok-123",
            get_org_id="org_42",
            get_org_name="Acme",
        )
        _start_patches(patches)
        try:
            from ember_code.session.core import Session

            session = Session(Settings(), project_dir=tmp_path)
            assert session.cloud_connected is True
            assert session.cloud_org_id == "org_42"
            assert session.cloud_org_name == "Acme"
        finally:
            _stop_patches(patches)


class TestSessionMessageHandling:
    @pytest.fixture
    def session(self, tmp_path):
        patches = _session_patches()
        _start_patches(patches)

        from ember_code.session.core import Session

        s = Session(Settings(), project_dir=tmp_path)

        # Configure mocks for message handling
        mock_hook_result = MagicMock()
        mock_hook_result.should_continue = True
        s.hook_executor.execute = AsyncMock(return_value=mock_hook_result)
        s.persistence.auto_name = AsyncMock()
        s.audit.log = MagicMock()

        # Mock the team response
        mock_response = MagicMock()
        mock_response.content = "Hello! I can help."
        mock_response.metrics = None
        s.main_team.arun = AsyncMock(return_value=mock_response)
        s.main_team.run_response = MagicMock(metrics=None)

        yield s
        _stop_patches(patches)

    @pytest.mark.asyncio
    async def test_handle_message_returns_response(self, session):
        with patch("ember_code.session.core.extract_response_text", return_value="Hello!"):
            result = await session.handle_message("Hi there")
            assert result == "Hello!"
            session.main_team.arun.assert_called_once_with("Hi there")

    @pytest.mark.asyncio
    async def test_handle_message_blocked_by_hook(self, session):
        mock_hook_result = MagicMock()
        mock_hook_result.should_continue = False
        mock_hook_result.message = "Blocked by policy"
        session.hook_executor.execute = AsyncMock(return_value=mock_hook_result)

        result = await session.handle_message("do something bad")
        assert "Blocked" in result
        session.main_team.arun.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_message_error(self, session):
        session.main_team.arun = AsyncMock(side_effect=RuntimeError("LLM failed"))
        result = await session.handle_message("test")
        assert "Error" in result


class TestSessionCompaction:
    @pytest.fixture
    def session(self, tmp_path):
        patches = _session_patches()
        _start_patches(patches)

        from ember_code.session.core import Session

        s = Session(Settings(), project_dir=tmp_path)
        yield s
        _stop_patches(patches)

    @pytest.mark.asyncio
    async def test_no_compaction_below_threshold(self, session):
        result = await session.compact_if_needed(1000, 10000)  # 10%
        assert result is False

    @pytest.mark.asyncio
    async def test_compacts_at_80_percent(self, session):
        session.main_team.num_history_runs = None
        session.main_team.session_summary_manager = None
        result = await session.compact_if_needed(8500, 10000)  # 85%
        assert result is True
        assert session.main_team.num_history_runs == 4

    @pytest.mark.asyncio
    async def test_no_compaction_when_already_minimal(self, session):
        session.main_team.num_history_runs = 2
        result = await session.compact_if_needed(9000, 10000)
        assert result is False


class TestSessionLearning:
    """Test that learning is wired into Session correctly."""

    def test_learning_none_when_disabled(self, tmp_path):
        patches = _session_patches()
        _start_patches(patches)
        try:
            from ember_code.session.core import Session

            settings = Settings()
            assert settings.learning.enabled is False
            session = Session(settings, project_dir=tmp_path)
            assert session._learning is None
        finally:
            _stop_patches(patches)

    def test_learning_created_when_enabled(self, tmp_path):
        fake_lm = MagicMock()
        patches = _session_patches(create_learning_machine=fake_lm)
        _start_patches(patches)
        try:
            from ember_code.session.core import Session

            settings = Settings()
            settings.learning.enabled = True
            session = Session(settings, project_dir=tmp_path)
            assert session._learning is fake_lm
        finally:
            _stop_patches(patches)

    def test_learning_passed_to_team(self, tmp_path):
        fake_lm = MagicMock()
        patches = _session_patches(create_learning_machine=fake_lm)
        mocks = {}
        for p in patches:
            mock = p.start()
            mocks[p.attribute] = mock
        if "ModelRegistry" in mocks:
            mocks["ModelRegistry"].return_value.get_context_window.return_value = 128_000
        try:
            from ember_code.session.core import Session

            settings = Settings()
            settings.learning.enabled = True
            Session(settings, project_dir=tmp_path)

            # Team() should have been called with learning=fake_lm
            team_cls = mocks["Team"]
            assert team_cls.called
            call_kwargs = team_cls.call_args[1]
            assert call_kwargs["learning"] is fake_lm
            assert call_kwargs["add_learnings_to_context"] is True
        finally:
            _stop_patches(patches)

    def test_learning_not_passed_when_disabled(self, tmp_path):
        patches = _session_patches()
        mocks = {}
        for p in patches:
            mock = p.start()
            mocks[p.attribute] = mock
        if "ModelRegistry" in mocks:
            mocks["ModelRegistry"].return_value.get_context_window.return_value = 128_000
        try:
            from ember_code.session.core import Session

            settings = Settings()
            Session(settings, project_dir=tmp_path)

            team_cls = mocks["Team"]
            call_kwargs = team_cls.call_args[1]
            assert call_kwargs["learning"] is None
            assert call_kwargs["add_learnings_to_context"] is False
        finally:
            _stop_patches(patches)

    def test_learning_applied_to_member_agents(self, tmp_path):
        fake_lm = MagicMock()
        patches = _session_patches(create_learning_machine=fake_lm)
        mocks = {}
        for p in patches:
            mock = p.start()
            mocks[p.attribute] = mock
        if "ModelRegistry" in mocks:
            mocks["ModelRegistry"].return_value.get_context_window.return_value = 128_000

        # Set up a mock member agent
        from agno.agent import Agent

        mock_agent = MagicMock(spec=Agent)
        pool_mock = mocks["AgentPool"].return_value
        pool_mock.get_member_agents.return_value = [mock_agent]

        try:
            from ember_code.session.core import Session

            settings = Settings()
            settings.learning.enabled = True
            Session(settings, project_dir=tmp_path)

            assert mock_agent.learning is fake_lm
            assert mock_agent.add_learnings_to_context is True
        finally:
            _stop_patches(patches)

    def test_learning_not_applied_to_members_when_disabled(self, tmp_path):
        patches = _session_patches()
        mocks = {}
        for p in patches:
            mock = p.start()
            mocks[p.attribute] = mock
        if "ModelRegistry" in mocks:
            mocks["ModelRegistry"].return_value.get_context_window.return_value = 128_000

        # Use a plain object to track attribute assignments
        class FakeAgent:
            pass

        mock_agent = FakeAgent()
        pool_mock = mocks["AgentPool"].return_value
        pool_mock.get_member_agents.return_value = [mock_agent]

        try:
            from ember_code.session.core import Session

            settings = Settings()
            Session(settings, project_dir=tmp_path)

            # learning should NOT have been set on the agent
            assert not hasattr(mock_agent, "learning")
        finally:
            _stop_patches(patches)
