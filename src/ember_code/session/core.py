"""Session core — wires up subsystems and handles messages."""

import getpass
import logging
import uuid
from pathlib import Path
from typing import Any

from agno.agent import Agent
from agno.compression.manager import CompressionManager
from agno.team.team import Team

from ember_code.auth.credentials import get_access_token, get_org_id, get_org_name
from ember_code.config.models import ModelRegistry
from ember_code.config.permissions import PermissionGuard
from ember_code.config.settings import Settings
from ember_code.config.tool_permissions import ToolPermissions
from ember_code.guardrails.runner import GuardrailRunner
from ember_code.hooks.events import HookEvent
from ember_code.hooks.executor import HookExecutor
from ember_code.hooks.loader import HookLoader
from ember_code.hooks.tool_hook import ToolEventHook
from ember_code.init import initialize_project
from ember_code.knowledge.manager import KnowledgeManager
from ember_code.learn import create_learning_machine
from ember_code.mcp.client import MCPClientManager
from ember_code.memory.manager import setup_db
from ember_code.pool import AgentPool
from ember_code.prompts import load_prompt
from ember_code.session.knowledge_ops import SessionKnowledgeManager
from ember_code.session.memory_ops import SessionMemoryManager
from ember_code.session.persistence import SessionPersistence
from ember_code.skills.loader import SkillPool
from ember_code.tools.registry import ToolRegistry
from ember_code.utils.audit import AuditLogger
from ember_code.utils.context import load_project_context
from ember_code.utils.display import print_error, print_info
from ember_code.utils.response import extract_response_text
from ember_code.workspace import WorkspaceManager

logger = logging.getLogger(__name__)


class Session:
    """Manages a single Ember Code session with all subsystem integrations.

    Session persistence and chat history are delegated entirely to Agno's
    native ``db`` / ``session_id`` mechanism.  The main team and all its
    members receive the same ``db`` and ``session_id``, so all turns are
    automatically persisted and restored.
    """

    def __init__(
        self,
        settings: Settings,
        project_dir: Path | None = None,
        resume_session_id: str | None = None,
        additional_dirs: list[Path] | None = None,
    ):
        self.settings = settings
        self.project_dir = project_dir or Path.cwd()
        self.workspace = WorkspaceManager(self.project_dir, additional_dirs)
        self.session_id = resume_session_id or str(uuid.uuid4())[:8]
        self.session_named = bool(resume_session_id)
        self.user_id = getpass.getuser()

        # ── First-run initialization (agents, skills, hooks, ember.md) ─
        initialize_project(self.project_dir)

        # ── Storage (Agno AsyncBaseDb) ────────────────────────────────
        self.db = setup_db(settings)

        # ── Knowledge (ChromaDB + Agno Knowledge) ─────────────────────
        self.knowledge = KnowledgeManager(settings, self.project_dir).create_knowledge()

        # ── Permission Guard ─────────────────────────────────────────
        self.permission_guard = PermissionGuard(settings)

        # ── Audit Logger ─────────────────────────────────────────────
        self.audit = AuditLogger(settings)

        # ── Hooks ────────────────────────────────────────────────────
        self._hook_loader = HookLoader(
            self.project_dir, cross_tool_support=settings.hooks.cross_tool_support
        )
        self.hooks_map = self._hook_loader.load()
        self.hook_executor = HookExecutor(self.hooks_map)

        # ── Project Context ──────────────────────────────────────────
        self.project_instructions = load_project_context(
            self.project_dir,
            settings.context.project_file,
            read_claude_md=settings.rules.cross_tool_support,
        )

        # ── Agent Pool (definitions only — agents built after MCP connects) ─
        self.pool = AgentPool()
        self.pool.load_definitions(settings, self.project_dir)
        if settings.orchestration.generate_ephemeral:
            self.pool.init_ephemeral(
                self.project_dir, settings.orchestration.max_ephemeral_per_session
            )
        self.pool.build_agents()  # initial build without MCP

        # ── Skill Pool ───────────────────────────────────────────────
        self.skill_pool = SkillPool()
        self.skill_pool.load_all(self.project_dir, settings.skills.cross_tool_support)

        # ── Context window (for compaction threshold, capped by setting) ──
        self._context_window = min(
            ModelRegistry(settings).get_context_window(),
            settings.models.max_context_window,
        )

        # ── Learning (Agno LearningMachine) ─────────────────────────
        self._learning = create_learning_machine(settings, self.db)

        # ── Ember Cloud auth (for CodeIndex + cloud indicator) ─────
        self._cloud_token = get_access_token(settings.auth.credentials_file)
        self._cloud_server_url = settings.auth.server_url
        self._cloud_org_id = get_org_id(settings.auth.credentials_file)
        self._cloud_org_name = get_org_name(settings.auth.credentials_file)

        # ── MCP Client Manager (user-configured servers only) ────────
        self.mcp_manager = MCPClientManager(self.project_dir)
        self._mcp_initialized = False

        # ── Guardrails ───────────────────────────────────────────────
        self.guardrail_runner = GuardrailRunner(settings)

        # ── Delegated managers ───────────────────────────────────────
        self.persistence = SessionPersistence(self.db, self.session_id)
        self.memory_mgr = SessionMemoryManager(self.db, settings, self.user_id)
        self.knowledge_mgr = SessionKnowledgeManager(self.knowledge, settings, self.project_dir)

        # ── Main Team (leader + specialist members) ──────────────────
        self.main_team = self._build_main_team()

    @property
    def cloud_connected(self) -> bool:
        """Whether the session is authenticated with Ember Cloud."""
        return self._cloud_token is not None

    @property
    def cloud_org_id(self) -> str | None:
        """The organization ID from the Ember Cloud JWT."""
        return self._cloud_org_id

    @property
    def cloud_org_name(self) -> str | None:
        """The organization display name from the Ember Cloud JWT."""
        return self._cloud_org_name

    def reload_hooks(self) -> int:
        """Reload hooks from settings files. Returns the number of hooks loaded."""
        self.hooks_map = self._hook_loader.load()
        self.hook_executor = HookExecutor(self.hooks_map)
        # Recreate tool event hook on the team
        tool_event_hook = self._create_tool_event_hook()
        if self.main_team:
            # Replace any existing ToolEventHook in the team's tool_hooks
            existing = self.main_team.tool_hooks or []
            self.main_team.tool_hooks = [h for h in existing if not isinstance(h, ToolEventHook)]
            self.main_team.tool_hooks.append(tool_event_hook)
        count = sum(len(hl) for hl in self.hooks_map.values())
        return count

    # ── Main Team setup ─────────────────────────────────────────────

    def _build_main_team(self) -> Team:
        """Build the main team with all Agno-native features configured.

        All settings (persistence, memory, streaming, etc.) are passed directly
        to the Team constructor — no intermediate AgnoFeatures layer.
        """
        # Leader tools
        registry = ToolRegistry(
            base_dir=str(self.project_dir),
            permissions=ToolPermissions(project_dir=self.project_dir),
            cloud_token=self._cloud_token,
            cloud_server_url=self._cloud_server_url,
            sandbox_shell=self.settings.safety.sandbox_shell,
            sandbox_allowed_network_commands=self.settings.safety.sandbox_allowed_network_commands,
        )
        leader_tool_names = [
            "Read",
            "Write",
            "Edit",
            "Bash",
            "Grep",
            "Glob",
            "Schedule",
            "NotebookEdit",
        ]
        for name in ("WebSearch", "WebFetch"):
            try:
                registry.resolve([name])
                leader_tool_names.append(name)
            except (ImportError, ValueError):
                pass
        # Add CodeIndex tools when connected to Ember Cloud
        if registry.cloud_connected:
            leader_tool_names.append("CodeIndex")
        leader_tools = registry.resolve(leader_tool_names)

        # Reasoning tools (optional)
        reasoning = _create_reasoning_tools(self.settings)
        if reasoning:
            leader_tools = [*leader_tools, reasoning]

        # Custom tools from .ember/tools/
        custom_toolkits = registry.load_custom_tools(self.project_dir)
        if custom_toolkits:
            leader_tools = [*leader_tools, *custom_toolkits]

        # Tool event hooks (PreToolUse/PostToolUse/PostToolUseFailure)
        tool_event_hook = self._create_tool_event_hook()

        # Members (all pool agents)
        members = self.pool.get_member_agents()

        # Apply session settings to all members
        for member in members:
            if isinstance(member, Agent):
                self._apply_settings(member, tool_event_hook=tool_event_hook)

        # System prompt (Agno auto-generates member descriptions in <member> XML)
        prompt = load_prompt("main_agent")

        # Append skill descriptions if any
        skill_descriptions = self.skill_pool.describe()
        if skill_descriptions and self.settings.skills.auto_trigger:
            prompt += "\n\n## Available Skills (user can invoke via /name)\n" + skill_descriptions

        # Model + context window (capped by settings to keep compression aggressive)
        model_registry = ModelRegistry(self.settings)
        model = model_registry.get_model()
        context_window = min(
            model_registry.get_context_window(),
            self.settings.models.max_context_window,
        )

        # Instructions
        instructions = [prompt]
        if self.project_instructions:
            instructions.append(f"Project instructions:\n{self.project_instructions}")

        # Persistent TODO — root only, loaded automatically
        todo_path = self.project_dir / ".ember" / "TODO.md"
        if todo_path.is_file():
            todo_content = todo_path.read_text().strip()
            if todo_content:
                instructions.append(f"Active TODO (.ember/TODO.md):\n{todo_content}")

        # Multi-workspace context
        workspace_ctx = self.workspace.get_context_instructions()
        if workspace_ctx:
            instructions.append(workspace_ctx)
            # Load project rules from additional directories
            for extra_dir in self.workspace.additional_dirs:
                extra_rules = load_project_context(
                    extra_dir,
                    self.settings.context.project_file,
                    read_claude_md=self.settings.rules.cross_tool_support,
                )
                if extra_rules:
                    instructions.append(f"Additional workspace ({extra_dir.name}):\n{extra_rules}")

        # Guardrails
        guardrails = _create_guardrails(self.settings)

        # Compression — triggers at 80% of context window
        compression = CompressionManager(
            model=model,
            compress_tool_results=True,
            compress_token_limit=int(context_window * 0.8),
        )

        team = Team(
            name="ember",
            mode="coordinate",
            model=model,
            members=members,
            tools=leader_tools,
            instructions=instructions,
            markdown=True,
            # Session persistence
            db=self.db,
            session_id=self.session_id,
            user_id=self.user_id,
            # History — grows freely, compacted when context fills up
            add_history_to_context=True,
            num_history_runs=None,
            max_tool_calls_from_history=0,
            # Memory
            enable_agentic_memory=self.settings.memory.enable_agentic_memory,
            add_memories_to_context=self.settings.memory.add_memories_to_context,
            # Compression — tool results compressed at 80% context
            compress_tool_results=True,
            compression_manager=compression,
            # Session summaries — covers conversation history
            enable_session_summaries=True,
            add_session_summary_to_context=True,
            # Streaming
            stream=True,
            stream_events=True,
            # Knowledge
            knowledge=self.knowledge,
            search_knowledge=self.knowledge is not None,
            # Guardrails
            pre_hooks=guardrails,
            # Learning
            learning=self._learning,
            add_learnings_to_context=self._learning is not None,
            # Tool event hooks
            tool_hooks=[tool_event_hook],
        )
        return team

    def _create_tool_event_hook(self) -> ToolEventHook:
        """Create a ToolEventHook for tool event hooks and protected path enforcement."""
        return ToolEventHook(
            executor=self.hook_executor,
            session_id=self.session_id,
            protected_paths=self.settings.safety.protected_paths,
        )

    def _apply_settings(self, agent: Agent, tool_event_hook: ToolEventHook) -> None:
        """Apply session settings to an individual agent."""
        if self.db is not None:
            agent.db = self.db
        agent.session_id = self.session_id
        agent.user_id = self.user_id
        agent.add_history_to_context = True
        agent.num_history_runs = None
        agent.enable_agentic_memory = self.settings.memory.enable_agentic_memory
        agent.add_memories_to_context = self.settings.memory.add_memories_to_context
        agent.compress_tool_results = True
        agent.enable_session_summaries = True
        agent.stream = True
        agent.stream_events = True
        if self.knowledge is not None:
            agent.knowledge = self.knowledge
            agent.search_knowledge = True
            from ember_code.tools.knowledge import KnowledgeTools

            knowledge_tools = KnowledgeTools(knowledge_mgr=self.knowledge_mgr)
            existing_tools = agent.tools or []
            agent.tools = [*existing_tools, knowledge_tools]
        if self._learning is not None:
            agent.learning = self._learning
            agent.add_learnings_to_context = True
        existing = agent.tool_hooks or []
        agent.tool_hooks = [*existing, tool_event_hook]

    # ── MCP initialization (async, runs once) ──────────────────────

    async def ensure_mcp(self) -> None:
        """Connect user-configured MCP servers and rebuild agents.

        Reads from .mcp.json / .ember/.mcp.json.  No auto-detection —
        only servers the user explicitly configured are connected.
        Runs once on first message.
        """
        if self._mcp_initialized:
            return
        self._mcp_initialized = True

        available = self.mcp_manager.list_servers()
        if not available:
            return

        clients: dict[str, Any] = {}
        for name in available:
            client = await self.mcp_manager.connect(name)
            if client is not None:
                clients[name] = client
            else:
                error = self.mcp_manager.get_error(name)
                print_info(f"MCP '{name}' connection failed: {error or 'unknown error'}")

        if not clients:
            return

        # Rebuild agents with MCP tools included, then rebuild main team
        self.pool.build_agents(mcp_clients=clients)
        self.main_team = self._build_main_team()

    # ── MCP status ─────────────────────────────────────────────────

    def get_mcp_status(self) -> list[tuple[str, bool]]:
        """Return list of (server_name, connected) for configured MCP servers."""
        available = set(self.mcp_manager.list_servers())
        connected = set(self.mcp_manager.list_connected())
        return [(name, name in connected) for name in available]

    # ── Dynamic context compaction ─────────────────────────────────

    async def compact_if_needed(self, input_tokens: int, context_window: int) -> bool:
        """Summarize conversation and trim history at 80% context usage.

        Tool result compression is handled automatically by Agno's
        ``CompressionManager`` (configured with ``compress_token_limit``).

        This method handles *conversation history* compaction:
        1. Generate/update the session summary (covers entire conversation)
        2. Set ``num_history_runs`` to keep only recent turns verbatim

        Returns True if compaction was applied.
        """
        if context_window <= 0 or input_tokens <= 0:
            return False

        usage = input_tokens / context_window
        if usage < 0.8:
            return False

        current = self.main_team.num_history_runs
        if current is not None and current <= 2:
            return False

        # Generate/update conversation summary before trimming
        ssm = self.main_team.session_summary_manager
        if ssm is not None:
            try:
                session = getattr(self.main_team, "_session", None)
                if session is not None:
                    await ssm.acreate_session_summary(session=session)
                    logger.info("Session summary generated before compaction")
            except Exception as e:
                logger.warning("Failed to generate session summary: %s", e)

        # Trim history — summary covers older turns
        new_limit = 4 if current is None else max(2, current // 2)

        self.main_team.num_history_runs = new_limit
        logger.info(
            "Context at %.0f%% — trimmed history to %d runs (summary covers older turns)",
            usage * 100,
            new_limit,
        )
        return True

    # ── Debug logging ─────────────────────────────────────────────────

    def _log_run_messages(self) -> None:
        """Dump messages from the last run for debugging tool result delivery."""
        try:
            rr = getattr(self.main_team, "run_response", None)
            if rr is None:
                logger.debug("RUN_MESSAGES: no run_response")
                return
            messages = getattr(rr, "messages", None)
            if not messages:
                logger.debug("RUN_MESSAGES: no messages in run_response")
                return
            logger.debug("RUN_MESSAGES: %d messages total", len(messages))
            for i, msg in enumerate(messages):
                role = getattr(msg, "role", "?")
                content = getattr(msg, "content", None)
                tool_calls = getattr(msg, "tool_calls", None)
                tool_call_id = getattr(msg, "tool_call_id", None)
                compressed = getattr(msg, "compressed_content", None)
                from_hist = getattr(msg, "from_history", False)

                content_str = str(content) if content is not None else "<None>"
                preview = content_str[:200]
                if len(content_str) > 200:
                    preview += f"... ({len(content_str)} total)"

                extras = []
                if tool_call_id:
                    extras.append(f"tcid={tool_call_id}")
                if tool_calls:
                    names = [tc.get("function", {}).get("name", "?") for tc in tool_calls]
                    extras.append(f"calls={names}")
                if compressed is not None:
                    extras.append(f"COMPRESSED({len(str(compressed))}ch)")
                if from_hist:
                    extras.append("HIST")

                logger.debug(
                    "  MSG[%d] role=%-9s %s | %s",
                    i,
                    role,
                    " ".join(extras),
                    preview,
                )
        except Exception as e:
            logger.debug("RUN_MESSAGES: error: %s", e)

    # ── Message handling (headless path) ──────────────────────────────

    async def handle_message(self, message: str) -> str:
        """Handle a single user message and return the response."""

        # ── Connect MCP servers on first message ──────────────────────
        await self.ensure_mcp()

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

        # ── Guardrails (inform, don't block) ──────────────────────────
        guardrail_prefix = ""
        if self.guardrail_runner.enabled:
            gr_results = await self.guardrail_runner.check(message)
            if gr_results:
                warnings = "; ".join(r.message for r in gr_results)
                guardrail_prefix = (
                    f"[GUARDRAIL WARNING] The following issues were detected in "
                    f"the user message: {warnings}\n"
                    f"Please be cautious and do not repeat or use any flagged content.\n\n"
                )
                logger.info("Guardrails triggered: %s", warnings)

        try:
            # ── Execute (Agno auto-persists via db) ──────────────────
            effective_message = guardrail_prefix + message if guardrail_prefix else message
            response = await self.main_team.arun(effective_message)
            self._log_run_messages()
            response_text = extract_response_text(response)

            # ── Auto-generate session name on first turn ─────────────
            if not self.session_named:
                await self.persistence.auto_name(self.main_team)
                self.session_named = True

            # ── Audit log ────────────────────────────────────────────
            self.audit.log(
                session_id=self.session_id,
                agent_name="ember",
                tool_name="main_team",
                status="success",
            )

            # ── Hook: Stop (can block up to 3 times) ─────────────────
            for _stop_attempt in range(3):
                stop_result = await self.hook_executor.execute(
                    event=HookEvent.STOP.value,
                    payload={
                        "session_id": self.session_id,
                        "response": response_text[:500],
                    },
                )
                if stop_result.should_continue:
                    break
                # Hook blocked — feed the rejection back to the agent
                feedback = stop_result.message or "Response blocked by Stop hook."
                system_msg = (
                    f"[SYSTEM] Your previous response was rejected by a Stop hook: "
                    f"{feedback}\nPlease revise your response to address this issue."
                )
                response = await self.main_team.arun(system_msg)
                response_text = extract_response_text(response)

            # ── Compact history if approaching context limit ─────────
            metrics = getattr(getattr(self.main_team, "run_response", None), "metrics", None)
            if metrics:
                input_tokens = getattr(metrics, "input_tokens", 0) or 0
                await self.compact_if_needed(input_tokens, self._context_window)

            return response_text

        except Exception as e:
            error_msg = f"Error handling message: {e}"
            print_error(error_msg)

            self.audit.log(
                session_id=self.session_id,
                agent_name="session",
                tool_name="main_team",
                status="error",
                details={"error": str(e)},
            )

            return error_msg


# ── Factory helpers ────────────────────────────────────────────────


def _create_reasoning_tools(settings: Settings) -> Any | None:
    """Create Agno ReasoningTools from config."""
    if not settings.reasoning.enabled:
        return None
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
