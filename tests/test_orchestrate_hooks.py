"""Tests for SubagentStart/SubagentStop hooks in OrchestrateTools."""

from unittest.mock import AsyncMock, MagicMock, patch

from ember_code.hooks.executor import HookExecutor
from ember_code.tools.orchestrate import OrchestrateTools


def _make_settings():
    """Create a minimal settings mock for OrchestrateTools."""
    settings = MagicMock()
    settings.orchestration.max_nesting_depth = 3
    settings.orchestration.max_total_agents = 20
    settings.orchestration.sub_team_timeout = 30
    settings.orchestration.max_task_iterations = 5
    return settings


def _make_pool(*agents):
    """Create a mock pool with named agents."""
    pool = MagicMock()
    agent_map = {}
    for agent in agents:
        agent_map[agent.name] = agent

    def get(name):
        if name not in agent_map:
            raise KeyError(f"Agent '{name}' not found")
        return agent_map[name]

    pool.get.side_effect = get
    return pool


class TestSubagentStartStop:
    """SubagentStart/SubagentStop hooks fire around agent/team execution."""

    def test_spawn_agent_fires_start_and_stop(self):
        """spawn_agent fires SubagentStart before and SubagentStop after."""
        executor = MagicMock(spec=HookExecutor)
        executor.execute = AsyncMock()

        agent = MagicMock()
        agent.name = "coder"
        agent.arun = AsyncMock(return_value=MagicMock(content="done"))
        pool = _make_pool(agent)

        tools = OrchestrateTools(
            pool=pool,
            settings=_make_settings(),
            hook_executor=executor,
            session_id="s1",
        )

        result = tools.spawn_agent(task="write code", agent_name="coder")
        assert "done" in result

        # Check SubagentStart was fired
        calls = executor.execute.call_args_list
        start_calls = [c for c in calls if c[1].get("event") == "SubagentStart"]
        stop_calls = [c for c in calls if c[1].get("event") == "SubagentStop"]
        assert len(start_calls) >= 1
        assert start_calls[0][1]["payload"]["agent_name"] == "coder"
        assert len(stop_calls) >= 1

    def test_spawn_agent_fires_stop_on_error(self):
        """SubagentStop fires even when the agent raises."""
        executor = MagicMock(spec=HookExecutor)
        executor.execute = AsyncMock()

        agent = MagicMock()
        agent.name = "buggy"
        agent.arun = AsyncMock(side_effect=RuntimeError("crash"))
        pool = _make_pool(agent)

        tools = OrchestrateTools(
            pool=pool,
            settings=_make_settings(),
            hook_executor=executor,
            session_id="s1",
        )

        result = tools.spawn_agent(task="do stuff", agent_name="buggy")
        assert "Error" in result

        calls = executor.execute.call_args_list
        stop_calls = [c for c in calls if c[1].get("event") == "SubagentStop"]
        assert len(stop_calls) >= 1
        assert "error" in stop_calls[0][1]["payload"]

    def test_no_hooks_when_no_executor(self):
        """Without hook_executor, SubagentStart/SubagentStop don't fire."""
        agent = MagicMock()
        agent.name = "coder"
        agent.arun = AsyncMock(return_value=MagicMock(content="ok"))
        pool = _make_pool(agent)

        tools = OrchestrateTools(
            pool=pool,
            settings=_make_settings(),
            # No hook_executor
        )

        result = tools.spawn_agent(task="code", agent_name="coder")
        assert "ok" in result

    def test_spawn_team_fires_hooks(self):
        """spawn_team fires SubagentStart/SubagentStop for the team."""
        executor = MagicMock(spec=HookExecutor)
        executor.execute = AsyncMock()

        agent1 = MagicMock()
        agent1.name = "a1"
        agent2 = MagicMock()
        agent2.name = "a2"
        pool = _make_pool(agent1, agent2)

        tools = OrchestrateTools(
            pool=pool,
            settings=_make_settings(),
            hook_executor=executor,
            session_id="s1",
        )

        with patch("agno.team.team.Team") as MockTeam:
            mock_team = MagicMock()
            mock_team.arun = AsyncMock(return_value=MagicMock(content="team result"))
            MockTeam.return_value = mock_team

            result = tools.spawn_team(task="plan", agent_names="a1,a2", mode="coordinate")
            assert "team result" in result

        calls = executor.execute.call_args_list
        start_calls = [c for c in calls if c[1].get("event") == "SubagentStart"]
        assert len(start_calls) >= 1
        assert "a1" in start_calls[0][1]["payload"]["agent_name"]
        assert "a2" in start_calls[0][1]["payload"]["agent_name"]

    def test_max_depth_skips_hooks(self):
        """When max depth reached, no hooks fire — just returns error."""
        executor = MagicMock(spec=HookExecutor)
        executor.execute = AsyncMock()

        settings = _make_settings()
        settings.orchestration.max_nesting_depth = 0  # Already at max

        tools = OrchestrateTools(
            pool=MagicMock(),
            settings=settings,
            current_depth=0,
            hook_executor=executor,
            session_id="s1",
        )

        result = tools.spawn_agent(task="x", agent_name="a")
        assert "Maximum nesting depth" in result
        executor.execute.assert_not_called()
