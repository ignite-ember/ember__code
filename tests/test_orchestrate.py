"""Tests for tools/orchestrate.py — agent and team spawning."""

from unittest.mock import AsyncMock, MagicMock, patch

from ember_code.tools.orchestrate import OrchestrateTools


def _mock_pool():
    pool = MagicMock()
    agent = MagicMock()
    agent.arun = AsyncMock(return_value=MagicMock(content="agent response"))
    pool.get.return_value = agent
    pool.agent_names = ["editor", "explorer", "reviewer"]
    return pool


def _mock_settings():
    settings = MagicMock()
    settings.orchestration.max_nesting_depth = 5
    settings.orchestration.max_total_agents = 20
    settings.orchestration.sub_team_timeout = 120
    settings.orchestration.max_task_iterations = 10
    return settings


class TestOrchestrateTools:
    def test_registers_functions(self):
        tools = OrchestrateTools(pool=_mock_pool(), settings=_mock_settings())
        names = set()
        for f in tools.functions.values():
            names.add(f.name)
        for f in tools.async_functions.values():
            names.add(f.name)
        assert "spawn_agent" in names
        assert "spawn_team" in names

    def test_spawn_agent_success(self):
        pool = _mock_pool()
        tools = OrchestrateTools(pool=pool, settings=_mock_settings())
        result = tools.spawn_agent("Fix the bug", "editor")
        assert "agent response" in result
        pool.get.assert_called_once_with("editor")

    def test_spawn_agent_unknown(self):
        pool = _mock_pool()
        pool.get.side_effect = KeyError("Agent 'nonexistent' not found in pool")
        tools = OrchestrateTools(pool=pool, settings=_mock_settings())
        result = tools.spawn_agent("task", "nonexistent")
        assert "not found" in result.lower() or "nonexistent" in result

    def test_spawn_agent_depth_limit(self):
        tools = OrchestrateTools(
            pool=_mock_pool(),
            settings=_mock_settings(),
            current_depth=10,  # exceeds max_nesting_depth of 5
        )
        result = tools.spawn_agent("task", "editor")
        assert "depth" in result.lower() or "nesting" in result.lower()

    def test_spawn_team_success(self):
        pool = _mock_pool()
        tools = OrchestrateTools(pool=pool, settings=_mock_settings())

        with patch("agno.team.team.Team") as MockTeam:
            mock_team_instance = MagicMock()
            mock_team_instance.arun = AsyncMock(return_value=MagicMock(content="team result"))
            MockTeam.return_value = mock_team_instance

            result = tools.spawn_team("implement feature", "editor,explorer", mode="coordinate")
            assert isinstance(result, str)
