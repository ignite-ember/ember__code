"""Session core — wires up subsystems and handles messages."""

import getpass
import uuid
from pathlib import Path
from typing import Any

from ember_code.config.permissions import PermissionGuard
from ember_code.config.settings import Settings
from ember_code.hooks.events import HookEvent
from ember_code.hooks.executor import HookExecutor
from ember_code.hooks.loader import load_hooks
from ember_code.knowledge.manager import setup_knowledge
from ember_code.memory.manager import setup_db
from ember_code.orchestrator import Orchestrator
from ember_code.pool import AgentPool
from ember_code.session.knowledge_ops import SessionKnowledgeManager
from ember_code.session.memory_ops import SessionMemoryManager
from ember_code.session.persistence import SessionPersistence
from ember_code.skills.loader import SkillPool
from ember_code.team_builder import AgnoFeatures, build_team
from ember_code.utils.audit import AuditLogger
from ember_code.utils.context import load_project_context
from ember_code.utils.display import print_error, print_info


class Session:
    """Manages a single Ember Code session with all subsystem integrations.

    Session persistence and chat history are delegated entirely to Agno's
    native ``db`` / ``session_id`` mechanism.  Every agent built by the
    ``TeamBuilder`` receives the same ``db`` and ``session_id``, so all
    turns are automatically persisted and restored.
    """

    def __init__(
        self,
        settings: Settings,
        project_dir: Path | None = None,
        resume_session_id: str | None = None,
    ):
        self.settings = settings
        self.project_dir = project_dir or Path.cwd()
        self.session_id = resume_session_id or str(uuid.uuid4())[:8]
        self.session_named = bool(resume_session_id)
        self.user_id = getpass.getuser()

        # ── Storage (Agno AsyncBaseDb) ────────────────────────────────
        self.db = setup_db(settings)

        # ── Knowledge (ChromaDB + Agno Knowledge) ─────────────────────
        self.knowledge = setup_knowledge(settings)

        # ── Permission Guard ─────────────────────────────────────────
        self.permission_guard = PermissionGuard(settings)

        # ── Audit Logger ─────────────────────────────────────────────
        self.audit = AuditLogger(settings)

        # ── Hooks ────────────────────────────────────────────────────
        self.hooks_map = load_hooks(self.project_dir)
        self.hook_executor = HookExecutor(self.hooks_map)

        # ── Project Context ──────────────────────────────────────────
        self.project_instructions = load_project_context(
            self.project_dir, settings.context.project_file
        )

        # ── Agent Pool ───────────────────────────────────────────────
        self.pool = AgentPool()
        self.pool.load_all(settings, self.project_dir)

        # ── Skill Pool ───────────────────────────────────────────────
        self.skill_pool = SkillPool()
        self.skill_pool.load_all(self.project_dir, settings.skills.cross_tool_support)

        # ── Orchestrator ─────────────────────────────────────────────
        skill_descriptions = self.skill_pool.describe()
        pool_description = self.pool.describe()
        if skill_descriptions and settings.skills.auto_trigger:
            pool_description += (
                "\n\n## Available Skills (user can invoke via /name)\n" + skill_descriptions
            )

        self.orchestrator = Orchestrator(
            pool_description=pool_description,
            settings=settings,
        )

        # ── Delegated managers ───────────────────────────────────────
        self.persistence = SessionPersistence(self.db, self.session_id)
        self.memory_mgr = SessionMemoryManager(self.db, settings, self.user_id)
        self.knowledge_mgr = SessionKnowledgeManager(self.knowledge, settings, self.project_dir)

    # ── AgnoFeatures factory ─────────────────────────────────────────

    def create_features(self) -> AgnoFeatures:
        """Create an ``AgnoFeatures`` instance wired to this session's db."""
        features = AgnoFeatures(self.settings)
        features.db = self.db
        features.session_id = self.session_id
        features.user_id = self.user_id
        if self.knowledge is not None:
            features.knowledge = self.knowledge
            features.search_knowledge = True
        return features

    # ── Message handling ─────────────────────────────────────────────

    async def handle_message(self, message: str) -> str:
        """Handle a single user message and return the response."""

        # ── Hook: UserPromptSubmit (can block) ───────────────────────
        hook_result = await self.hook_executor.execute(
            event=HookEvent.USER_PROMPT_SUBMIT.value,
            payload={"message": message, "session_id": self.session_id},
        )
        if not hook_result.should_continue:
            blocked_msg = hook_result.message or "Blocked by UserPromptSubmit hook."
            self.audit.log(
                session_id=self.session_id,
                agent_name="session",
                tool_name="user_prompt",
                status="BLOCKED",
                details={"reason": blocked_msg},
            )
            return blocked_msg

        try:
            # ── Orchestrator decides on team composition ─────────────
            plan = await self.orchestrator.plan(
                message=message,
                session_id=self.session_id,
                project_instructions=self.project_instructions,
            )

            if self.settings.display.show_routing:
                print_info(f"Team: {plan.team_name} ({plan.team_mode}) -> {plan.agent_names}")

            # ── Build team with Agno-native session features ─────────
            features = self.create_features()
            executor = build_team(plan, self.pool, features=features)

            # ── Execute (Agno auto-persists via db) ──────────────────
            if hasattr(executor, "arun"):
                response = await executor.arun(message)
            else:
                response = executor.run(message)

            response_text = self._extract_response_text(response)

            # ── Auto-generate session name on first turn ─────────────
            if not self.session_named:
                await self.persistence.auto_name(executor)
                self.session_named = True

            # ── Audit log ────────────────────────────────────────────
            self.audit.log(
                session_id=self.session_id,
                agent_name=plan.team_name,
                tool_name="orchestrator",
                status="success",
                details={
                    "team_mode": plan.team_mode,
                    "agents": plan.agent_names,
                },
            )

            # ── Hook: Stop ───────────────────────────────────────────
            await self.hook_executor.execute(
                event=HookEvent.STOP.value,
                payload={
                    "session_id": self.session_id,
                    "response": response_text[:500],
                },
            )

            return response_text

        except Exception as e:
            error_msg = f"Error handling message: {e}"
            print_error(error_msg)

            self.audit.log(
                session_id=self.session_id,
                agent_name="session",
                tool_name="orchestrator",
                status="error",
                details={"error": str(e)},
            )

            return error_msg

    def _extract_response_text(self, response: Any) -> str:
        """Extract text from an Agno response object."""
        if isinstance(response, str):
            return response
        if hasattr(response, "content"):
            content = response.content
            if isinstance(content, str):
                return content
            return str(content)
        if hasattr(response, "messages"):
            for msg in reversed(response.messages):
                if hasattr(msg, "content") and msg.content:
                    return str(msg.content)
        return str(response)
