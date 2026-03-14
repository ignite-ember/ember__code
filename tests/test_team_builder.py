"""Tests for the refactored TeamBuilder with AgnoFeatures."""

import pytest
from agno.agent import Agent
from agno.team.team import Team

from ember_code.schemas import TeamPlan
from ember_code.team_builder import AgnoFeatures, TeamBuilder, build_team

# ── AgnoFeatures ──────────────────────────────────────────────────


class TestAgnoFeatures:
    def test_defaults(self):
        f = AgnoFeatures()
        assert f.db is None
        assert f.session_id is None
        assert f.user_id is None
        assert f.add_history_to_context is True
        assert f.num_history_runs == 10
        assert f.read_chat_history is True
        assert f.enable_agentic_memory is True
        assert f.add_memories_to_context is True
        assert f.compress_tool_results is True
        assert f.enable_session_summaries is True
        assert f.stream is True
        assert f.stream_events is True
        assert f.tool_hooks is None

    def test_apply_to_agent(self):
        f = AgnoFeatures()
        agent = Agent(name="test")
        f.apply_to_agent(agent)
        assert agent.compress_tool_results is True
        assert agent.enable_session_summaries is True
        assert agent.add_history_to_context is True
        assert agent.num_history_runs == 10
        assert agent.read_chat_history is True
        assert agent.enable_agentic_memory is True
        assert agent.add_memories_to_context is True

    def test_apply_db_and_session_id(self):
        f = AgnoFeatures()
        f.db = "fake-db"
        f.session_id = "sess-123"
        agent = Agent(name="test")
        f.apply_to_agent(agent)
        assert agent.db == "fake-db"
        assert agent.session_id == "sess-123"

    def test_apply_skips_none_db(self):
        f = AgnoFeatures()
        agent = Agent(name="test")
        original_db = agent.db
        f.apply_to_agent(agent)
        assert agent.db == original_db  # unchanged

    def test_apply_tool_hooks(self):
        def my_hook():
            pass

        f = AgnoFeatures()
        f.tool_hooks = [my_hook]
        agent = Agent(name="test")
        f.apply_to_agent(agent)
        assert agent.tool_hooks == [my_hook]

    def test_apply_to_team(self):
        f = AgnoFeatures()
        f.db = "fake-db"
        f.session_id = "sess-456"
        f.user_id = "bob"
        agent1 = Agent(name="a1")
        agent2 = Agent(name="a2")
        team = Team(name="t", members=[agent1, agent2], mode="coordinate")
        f.apply_to_team(team)
        # Team-level features
        assert team.db == "fake-db"
        assert team.session_id == "sess-456"
        assert team.user_id == "bob"
        assert team.add_history_to_context is True
        assert team.num_history_runs == 10
        assert team.read_chat_history is True
        assert team.enable_agentic_memory is True
        assert team.add_memories_to_context is True
        assert team.compress_tool_results is True
        assert team.enable_session_summaries is True
        # Members should also have full features applied
        assert agent1.compress_tool_results is True
        assert agent2.compress_tool_results is True
        assert agent1.db == "fake-db"
        assert agent2.session_id == "sess-456"
        assert agent1.user_id == "bob"

    def test_apply_to_team_skips_none_db(self):
        f = AgnoFeatures()
        team = Team(name="t", members=[Agent(name="a1")], mode="coordinate")
        original_db = team.db
        f.apply_to_team(team)
        assert team.db == original_db

    def test_apply_to_team_tool_hooks(self):
        def hook():
            pass

        f = AgnoFeatures()
        f.tool_hooks = [hook]
        team = Team(name="t", members=[Agent(name="a1")], mode="coordinate")
        f.apply_to_team(team)
        assert team.tool_hooks == [hook]

    def test_apply_to_team_memory_disabled(self):
        f = AgnoFeatures()
        f.enable_agentic_memory = False
        f.add_memories_to_context = False
        team = Team(name="t", members=[Agent(name="a1")], mode="coordinate")
        f.apply_to_team(team)
        assert team.enable_agentic_memory is False
        assert team.add_memories_to_context is False

    def test_from_settings_max_history_runs(self):
        from ember_code.config.settings import Settings, StorageConfig

        settings = Settings(storage=StorageConfig(max_history_runs=5))
        f = AgnoFeatures(settings)
        assert f.num_history_runs == 5

    def test_from_settings_memory_config(self):
        from ember_code.config.settings import MemoryConfig, Settings

        settings = Settings(
            memory=MemoryConfig(
                enable_agentic_memory=False,
                add_memories_to_context=False,
            )
        )
        f = AgnoFeatures(settings)
        assert f.enable_agentic_memory is False
        assert f.add_memories_to_context is False

    def test_agentic_memory_applied_to_agent(self):
        f = AgnoFeatures()
        f.enable_agentic_memory = True
        f.add_memories_to_context = True
        agent = Agent(name="test")
        f.apply_to_agent(agent)
        assert agent.enable_agentic_memory is True
        assert agent.add_memories_to_context is True

    def test_agentic_memory_disabled(self):
        f = AgnoFeatures()
        f.enable_agentic_memory = False
        agent = Agent(name="test")
        f.apply_to_agent(agent)
        assert agent.enable_agentic_memory is False

    def test_user_id_applied_to_agent(self):
        f = AgnoFeatures()
        f.user_id = "alice"
        agent = Agent(name="test")
        f.apply_to_agent(agent)
        assert agent.user_id == "alice"

    def test_user_id_skips_none(self):
        f = AgnoFeatures()
        agent = Agent(name="test")
        original = agent.user_id
        f.apply_to_agent(agent)
        assert agent.user_id == original


# ── TeamBuilder ───────────────────────────────────────────────────


class TestTeamBuilder:
    @pytest.fixture
    def mock_pool(self):
        """A minimal mock AgentPool."""

        class MockPool:
            def __init__(self):
                self._agents = {
                    "editor": Agent(name="editor"),
                    "reviewer": Agent(name="reviewer"),
                    "conversational": Agent(name="conversational"),
                }

            def get(self, name):
                if name not in self._agents:
                    raise KeyError(f"Agent not found: '{name}'")
                return self._agents[name]

        return MockPool()

    def test_build_single(self, mock_pool):
        plan = TeamPlan(
            team_name="test",
            team_mode="single",
            agent_names=["editor"],
            reasoning="test",
        )
        builder = TeamBuilder(mock_pool)
        result = builder.build(plan)
        assert isinstance(result, Agent)
        assert result.name == "editor"
        # Agno features applied
        assert result.compress_tool_results is True

    def test_build_empty_falls_back(self, mock_pool):
        plan = TeamPlan(
            team_name="test",
            team_mode="single",
            agent_names=[],
            reasoning="test",
        )
        builder = TeamBuilder(mock_pool)
        result = builder.build(plan)
        assert isinstance(result, Agent)
        assert result.name == "conversational"

    def test_build_team(self, mock_pool):
        plan = TeamPlan(
            team_name="review-team",
            team_mode="coordinate",
            agent_names=["editor", "reviewer"],
            reasoning="review task",
        )
        builder = TeamBuilder(mock_pool)
        result = builder.build(plan)
        assert isinstance(result, Team)
        assert result.name == "review-team"
        assert result.compress_tool_results is True

    def test_build_with_custom_features(self, mock_pool):
        features = AgnoFeatures()
        features.compress_tool_results = False
        features.enable_session_summaries = False

        plan = TeamPlan(
            team_name="test",
            team_mode="single",
            agent_names=["editor"],
            reasoning="test",
        )
        builder = TeamBuilder(mock_pool, features)
        result = builder.build(plan)
        assert result.compress_tool_results is False
        assert result.enable_session_summaries is False

    def test_build_team_convenience(self, mock_pool):
        plan = TeamPlan(
            team_name="test",
            team_mode="single",
            agent_names=["editor"],
            reasoning="test",
        )
        result = build_team(plan, mock_pool)
        assert isinstance(result, Agent)
        assert result.compress_tool_results is True
