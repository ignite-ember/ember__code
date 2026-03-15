"""Team Builder — constructs Agno Teams or single Agents from a TeamPlan."""

import logging
from typing import Any

from agno.agent import Agent
from agno.team.team import Team

from ember_code.config.settings import Settings
from ember_code.pool import AgentPool
from ember_code.schemas import TeamPlan

logger = logging.getLogger(__name__)


class AgnoFeatures:
    """Configuration for Agno-native features applied to agents and teams.

    Encapsulates session persistence (``db``, ``session_id``), history
    management, agentic memory, knowledge, learning, reasoning tools,
    guardrails, compression, session summaries, and streaming settings
    so they are passed consistently across all executors.
    """

    def __init__(self, settings: Settings | None = None):
        # Session persistence
        self.db: Any | None = None
        self.session_id: str | None = None
        self.user_id: str | None = None

        # History management
        self.add_history_to_context: bool = True
        self.num_history_runs: int = 10
        self.read_chat_history: bool = True

        # Agentic memory — agent gets an update_user_memory tool
        self.enable_agentic_memory: bool = True
        self.add_memories_to_context: bool = True

        # Compression & summaries
        self.compress_tool_results: bool = True
        self.enable_session_summaries: bool = True

        # Streaming
        self.stream: bool = True
        self.stream_events: bool = True

        # Hooks
        self.tool_hooks: list | None = None

        # Knowledge
        self.knowledge: Any | None = None
        self.search_knowledge: bool = False

        # Learning (Agno LearningMachine)
        self.learning: bool = False

        # Reasoning tools
        self.reasoning_tools: Any | None = None

        # Guardrails (pre_hooks)
        self.pre_hooks: list | None = None

        if settings:
            self._configure_from_settings(settings)

    def _configure_from_settings(self, settings: Settings) -> None:
        """Override defaults from user settings."""
        self.num_history_runs = settings.storage.max_history_runs
        self.enable_agentic_memory = settings.memory.enable_agentic_memory
        self.add_memories_to_context = settings.memory.add_memories_to_context

        # Learning
        self.learning = settings.learning.enabled

        # Reasoning tools
        if settings.reasoning.enabled:
            self.reasoning_tools = _create_reasoning_tools(settings)

        # Guardrails
        guardrails = _create_guardrails(settings)
        if guardrails:
            self.pre_hooks = guardrails

    def apply_to_agent(self, agent: Agent) -> Agent:
        """Apply Agno-native features to an agent in-place."""
        # Session persistence — Agno auto-loads and auto-saves
        if self.db is not None:
            agent.db = self.db
        if self.session_id is not None:
            agent.session_id = self.session_id
        if self.user_id is not None:
            agent.user_id = self.user_id

        # History management
        agent.add_history_to_context = self.add_history_to_context
        agent.num_history_runs = self.num_history_runs
        agent.read_chat_history = self.read_chat_history

        # Agentic memory
        agent.enable_agentic_memory = self.enable_agentic_memory
        agent.add_memories_to_context = self.add_memories_to_context

        # Compression & summaries
        agent.compress_tool_results = self.compress_tool_results
        agent.enable_session_summaries = self.enable_session_summaries

        # Streaming — must set stream_events so tool/token events are yielded
        agent.stream = self.stream
        agent.stream_events = self.stream_events

        if self.tool_hooks:
            agent.tool_hooks = self.tool_hooks

        # Knowledge
        if self.knowledge is not None:
            agent.knowledge = self.knowledge
            agent.search_knowledge = self.search_knowledge

        # Learning
        if self.learning:
            agent.learning = True

        # Reasoning tools — append to agent's existing tools
        if self.reasoning_tools is not None:
            if agent.tools is None:
                agent.tools = []
            agent.tools.append(self.reasoning_tools)

        # Guardrails (pre_hooks)
        if self.pre_hooks:
            if agent.pre_hooks is None:
                agent.pre_hooks = []
            agent.pre_hooks.extend(self.pre_hooks)

        return agent

    def apply_to_team(self, team: Team) -> Team:
        """Apply Agno-native features to a team and its members."""
        # Session persistence
        if self.db is not None:
            team.db = self.db
        if self.session_id is not None:
            team.session_id = self.session_id
        if self.user_id is not None:
            team.user_id = self.user_id

        # History management
        team.add_history_to_context = self.add_history_to_context
        team.num_history_runs = self.num_history_runs
        team.read_chat_history = self.read_chat_history

        # Agentic memory
        team.enable_agentic_memory = self.enable_agentic_memory
        team.add_memories_to_context = self.add_memories_to_context

        # Compression & summaries
        team.compress_tool_results = self.compress_tool_results
        team.enable_session_summaries = self.enable_session_summaries

        # Streaming
        team.stream = self.stream
        team.stream_events = self.stream_events

        if self.tool_hooks:
            team.tool_hooks = self.tool_hooks

        # Knowledge — applied at team level so the team leader can search
        if self.knowledge is not None:
            team.knowledge = self.knowledge
            team.search_knowledge = self.search_knowledge

        # Guardrails on team
        if self.pre_hooks:
            if team.pre_hooks is None:
                team.pre_hooks = []
            team.pre_hooks.extend(self.pre_hooks)

        # Also apply to individual members
        for member in team.members:
            if isinstance(member, Agent):
                self.apply_to_agent(member)
        return team


# ── Factory helpers ────────────────────────────────────────────────


def _create_reasoning_tools(settings: Settings) -> Any | None:
    """Create Agno ReasoningTools from config."""
    try:
        from agno.tools.reasoning import ReasoningTools

        return ReasoningTools(
            add_instructions=settings.reasoning.add_instructions,
            add_few_shot=settings.reasoning.add_few_shot,
        )
    except ImportError:
        logger.debug("agno.tools.reasoning not available")
        return None


def _create_guardrails(settings: Settings) -> list | None:
    """Create Agno guardrail pre_hooks from config."""
    hooks: list = []
    cfg = settings.guardrails

    if cfg.pii_detection:
        try:
            from agno.guardrails.pii import PIIDetectionGuardrail

            hooks.append(PIIDetectionGuardrail())
        except ImportError:
            logger.debug("agno.guardrails.pii not available")

    if cfg.prompt_injection:
        try:
            from agno.guardrails.prompt_injection import PromptInjectionGuardrail

            hooks.append(PromptInjectionGuardrail())
        except ImportError:
            logger.debug("agno.guardrails.prompt_injection not available")

    if cfg.moderation:
        try:
            from agno.guardrails.openai import OpenAIModerationGuardrail

            hooks.append(OpenAIModerationGuardrail())
        except ImportError:
            logger.debug("agno.guardrails.openai not available")

    return hooks if hooks else None


class TeamBuilder:
    """Builds Agno Teams or single Agents from TeamPlans.

    Applies Agno-native features (compression, session summaries,
    streaming) automatically to all executors.
    """

    def __init__(self, pool: AgentPool, features: AgnoFeatures | None = None):
        self.pool = pool
        self.features = features or AgnoFeatures()

    def build(self, plan: TeamPlan) -> Agent | Team:
        """Build an Agno Team or single Agent from a TeamPlan."""
        if not plan.agent_names:
            agent = self.pool.get("conversational")
            return self.features.apply_to_agent(agent)

        if plan.team_mode == "single" or len(plan.agent_names) == 1:
            return self._build_single(plan)

        return self._build_team(plan)

    def _build_single(self, plan: TeamPlan) -> Agent:
        """Build a single agent with optional dynamic instructions."""
        agent = self.pool.get(plan.agent_names[0])
        if plan.team_instructions:
            if agent.instructions:
                agent.instructions.extend(plan.team_instructions)
            else:
                agent.instructions = plan.team_instructions
        return self.features.apply_to_agent(agent)

    def _build_team(self, plan: TeamPlan) -> Team:
        """Build a multi-agent team."""
        members = [self.pool.get(name) for name in plan.agent_names]

        mode = plan.team_mode
        if mode not in ("route", "coordinate", "broadcast"):
            mode = "coordinate"

        team = Team(
            name=plan.team_name,
            mode=mode,
            members=members,
            instructions=plan.team_instructions if plan.team_instructions else None,
            markdown=True,
        )
        return self.features.apply_to_team(team)


# Convenience function for backward compatibility
def build_team(
    plan: TeamPlan,
    pool: AgentPool,
    settings: Settings | None = None,
    features: AgnoFeatures | None = None,
) -> Agent | Team:
    """Convenience wrapper around TeamBuilder.build()."""
    if features is None:
        features = AgnoFeatures(settings)
    builder = TeamBuilder(pool, features)
    return builder.build(plan)
