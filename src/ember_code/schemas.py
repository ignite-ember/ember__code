"""Pydantic schemas for orchestration and team planning."""

from typing import Literal

from pydantic import BaseModel, Field


class TeamPlan(BaseModel):
    """The Orchestrator's decision on how to handle a task."""

    team_name: str = Field(description="Descriptive name for this team")
    team_mode: Literal["single", "route", "coordinate", "broadcast", "tasks"] = Field(
        description="How agents interact"
    )
    agent_names: list[str] = Field(description="Agents to include from the pool")
    team_instructions: list[str] = Field(
        default_factory=list,
        description="Dynamic instructions for the team leader",
    )
    reasoning: str = Field(description="Why this configuration was chosen")
