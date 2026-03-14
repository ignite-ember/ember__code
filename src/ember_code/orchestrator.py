"""Orchestrator — meta-agent that analyzes tasks and assembles teams."""

from agno.agent import Agent

from ember_code.config.models import ModelRegistry
from ember_code.config.settings import Settings
from ember_code.prompts import load_prompt
from ember_code.schemas import TeamPlan


class Orchestrator:
    """Meta-agent that analyzes tasks and decides on team composition."""

    def __init__(
        self,
        pool_description: str,
        settings: Settings,
        system_prompt: str | None = None,
    ):
        self.settings = settings
        self.pool_description = pool_description
        self.system_prompt = system_prompt or load_prompt("orchestrator")

        model = ModelRegistry(settings).get_model()

        prompt = self.system_prompt.format(agent_descriptions=pool_description)

        self._planner = Agent(
            name="orchestrator",
            model=model,
            instructions=[prompt],
            response_model=TeamPlan,
            markdown=True,
        )

    async def plan(
        self,
        message: str,
        context: str = "",
        session_id: str | None = None,
        project_instructions: str = "",
    ) -> TeamPlan:
        """Analyze a message and produce a TeamPlan."""
        prompt_parts = []
        if project_instructions:
            prompt_parts.append(f"Project instructions:\n{project_instructions[:500]}\n")
        if context:
            prompt_parts.append(f"Conversation context:\n{context}\n")
        prompt_parts.append(f"User message: {message}")

        full_prompt = "\n".join(prompt_parts)
        response = await self._planner.arun(full_prompt)

        if hasattr(response, "content") and isinstance(response.content, TeamPlan):
            return response.content

        return TeamPlan(
            team_name="fallback",
            team_mode="single",
            agent_names=["conversational"],
            team_instructions=[],
            reasoning="Fallback: could not parse orchestrator response",
        )
