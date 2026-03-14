"""Tests for orchestrator.py and team_builder.py."""

import pytest

from ember_code.schemas import TeamPlan
from ember_code.team_builder import TeamBuilder


class TestTeamPlan:
    def test_create_single_plan(self):
        plan = TeamPlan(
            team_name="editor-solo",
            team_mode="single",
            agent_names=["editor"],
            reasoning="Simple edit task",
        )
        assert plan.team_name == "editor-solo"
        assert plan.team_mode == "single"
        assert plan.agent_names == ["editor"]
        assert plan.team_instructions == []

    def test_create_coordinate_plan(self):
        plan = TeamPlan(
            team_name="feature-team",
            team_mode="coordinate",
            agent_names=["planner", "editor", "reviewer"],
            team_instructions=["Write tests first"],
            reasoning="Multi-step feature",
        )
        assert plan.team_mode == "coordinate"
        assert len(plan.agent_names) == 3
        assert "Write tests first" in plan.team_instructions

    def test_all_modes_valid(self):
        for mode in ("single", "route", "coordinate", "broadcast", "tasks"):
            plan = TeamPlan(
                team_name="test",
                team_mode=mode,
                agent_names=["a"],
                reasoning="test",
            )
            assert plan.team_mode == mode

    def test_invalid_mode_rejected(self):
        with pytest.raises(ValueError):
            TeamPlan(
                team_name="test",
                team_mode="invalid_mode",
                agent_names=["a"],
                reasoning="test",
            )


class TestTeamBuilder:
    def test_build_single_agent(self, tmp_path, settings):
        from ember_code.pool import AgentPool

        (tmp_path / "editor.md").write_text(
            "---\nname: editor\ndescription: Code editor\n---\nEdit code.\n"
        )
        pool = AgentPool()
        pool.load_directory(tmp_path, priority=0, settings=settings)

        plan = TeamPlan(
            team_name="solo",
            team_mode="single",
            agent_names=["editor"],
            reasoning="Just editing",
        )

        builder = TeamBuilder(pool)
        result = builder.build(plan)
        assert result.name == "editor"

    def test_build_empty_plan_falls_back(self, tmp_path, settings):
        from ember_code.pool import AgentPool

        (tmp_path / "conversational.md").write_text(
            "---\nname: conversational\ndescription: Chat\n---\nChat.\n"
        )
        pool = AgentPool()
        pool.load_directory(tmp_path, priority=0, settings=settings)

        plan = TeamPlan(
            team_name="empty",
            team_mode="single",
            agent_names=[],
            reasoning="No agents",
        )

        builder = TeamBuilder(pool)
        result = builder.build(plan)
        assert result.name == "conversational"

    def test_build_team_coordinate(self, tmp_path, settings):
        from ember_code.pool import AgentPool

        for name in ["alpha", "beta"]:
            (tmp_path / f"{name}.md").write_text(
                f"---\nname: {name}\ndescription: Agent {name}\n---\n"
            )
        pool = AgentPool()
        pool.load_directory(tmp_path, priority=0, settings=settings)

        plan = TeamPlan(
            team_name="duo",
            team_mode="coordinate",
            agent_names=["alpha", "beta"],
            reasoning="Need both",
        )

        builder = TeamBuilder(pool)
        result = builder.build(plan)
        # Should be a Team, not an Agent
        assert hasattr(result, "members")
        assert result.name == "duo"
