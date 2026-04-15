"""Session core — wires up subsystems and handles messages."""

import asyncio
import getpass
import logging
import uuid
from pathlib import Path
from typing import Any

from agno.agent import Agent
from agno.compression.manager import CompressionManager

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
        pre_knowledge: Any | None = None,
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
        # Pre-loaded before Textual starts (SentenceTransformer spawns
        # subprocesses that crash inside Textual's restricted fd env).
        self.knowledge = pre_knowledge
        self._knowledge_loading = pre_knowledge is not None
        self._knowledge_event: asyncio.Event | None = None
        self._knowledge_error: str | None = None

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
        # Share knowledge_mgr with the pool so all sub-agents get knowledge tools
        self.pool._knowledge_mgr = self.knowledge_mgr if self.knowledge else None

        # ── Turn counter (for periodic memory extraction) ──────────
        self._turn_count = 0
        self._memory_interval = 10  # extract memories every N turns
        self._recent_messages: list[str] = []  # buffer for memory extraction
        self._memory_manager = self._create_memory_manager()

        # ── Main Agent (single agent with all tools + orchestration) ──
        self.main_team = self._build_main_agent()

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

    # ── Main Agent setup ────────────────────────────────────────────

    def _build_main_agent(self) -> Agent:
        """Build the main agent with all tools and orchestration capability.

        A single agent handles everything directly. When it needs a
        specialist, it calls spawn_agent() or spawn_team() via the
        OrchestrateTools toolkit — Agno handles sub-team execution.
        """
        # Core tools
        registry = ToolRegistry(
            base_dir=str(self.project_dir),
            permissions=ToolPermissions(project_dir=self.project_dir),
            cloud_token=self._cloud_token,
            cloud_server_url=self._cloud_server_url,
            sandbox_shell=self.settings.safety.sandbox_shell,
            sandbox_allowed_network_commands=self.settings.safety.sandbox_allowed_network_commands,
        )
        tool_names = [
            "Read",
            "Write",
            "Edit",
            "Bash",
            "Grep",
            "Glob",
            "Schedule",
            "NotebookEdit",
        ]
        web_allowed = (
            self.settings.permissions.web_search != "deny"
            and not self.settings.safety.sandbox_shell
        )
        fetch_allowed = (
            self.settings.permissions.web_fetch != "deny" and not self.settings.safety.sandbox_shell
        )
        if web_allowed:
            try:
                registry.resolve(["WebSearch"])
                tool_names.append("WebSearch")
            except (ImportError, ValueError):
                pass
        if fetch_allowed:
            try:
                registry.resolve(["WebFetch"])
                tool_names.append("WebFetch")
            except (ImportError, ValueError):
                pass
        # TODO: Enable CodeIndex when the service is online
        # if registry.cloud_connected:
        #     tool_names.append("CodeIndex")
        tools = registry.resolve(tool_names)

        # Orchestration tools — lets the agent delegate to specialists
        from ember_code.tools.orchestrate import OrchestrateTools

        orchestrate = OrchestrateTools(
            pool=self.pool,
            settings=self.settings,
            current_depth=0,
            hook_executor=self.hook_executor,
            session_id=self.session_id,
        )
        tools.append(orchestrate)

        # Reasoning tools (optional)
        reasoning = _create_reasoning_tools(self.settings)
        if reasoning:
            tools.append(reasoning)

        # Knowledge tools — lets agents search, add, and manage knowledge
        if self.knowledge is not None:
            from ember_code.tools.knowledge import KnowledgeTools

            tools.append(KnowledgeTools(self.knowledge_mgr))

        # MCP tools — connected MCP server clients
        connected_mcp = self.mcp_manager.list_connected()
        for mcp_name in connected_mcp:
            client = self.mcp_manager._clients.get(mcp_name)
            if client and client not in tools:
                tools.append(client)

        # Custom tools from .ember/tools/
        custom_toolkits = registry.load_custom_tools(self.project_dir)
        if custom_toolkits:
            tools.extend(custom_toolkits)

        # Tool event hooks (PreToolUse/PostToolUse/PostToolUseFailure)
        tool_event_hook = self._create_tool_event_hook()

        # System prompt with substitutions
        prompt = load_prompt("main_agent")
        prompt = prompt.replace(
            "{{AGENT_CATALOG}}", self._build_agent_catalog() or "(no agents loaded)"
        )

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

        agent = Agent(
            name="ember",
            model=model,
            tools=tools,
            instructions=instructions,
            markdown=True,
            # Session persistence
            db=self.db,
            session_id=self.session_id,
            user_id=self.user_id,
            # History — keep all turns until 80% compaction triggers
            add_history_to_context=True,
            num_history_runs=10000,
            # Memory — disabled on agent (no per-turn tools/extraction);
            # we trigger extraction periodically (every N turns) ourselves.
            # Memories are still loaded into context via add_memories_to_context.
            enable_agentic_memory=False,
            add_memories_to_context=self.settings.memory.add_memories_to_context,
            # Compression
            compress_tool_results=True,
            compression_manager=compression,
            # Session summaries — disabled at init to avoid per-turn LLM calls.
            # _compact() creates the manager on demand. Existing summaries
            # from prior compaction are still injected if present.
            enable_session_summaries=False,
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
        return agent

    def _build_agent_catalog(self) -> str:
        """Build a text catalog of specialist agents for the system prompt."""
        lines = []
        for defn in self.pool.list_agents():
            tools_str = ", ".join(defn.tools) if defn.tools else "none"
            lines.append(f"- **{defn.name}**: {defn.description} (tools: {tools_str})")
        return "\n".join(lines)

    def _create_memory_manager(self) -> Any | None:
        """Create a standalone memory manager for periodic extraction."""
        if not self.settings.memory.enable_agentic_memory or self.db is None:
            return None
        try:
            from agno.memory.manager import MemoryManager

            model_registry = ModelRegistry(self.settings)
            return MemoryManager(
                model=model_registry.get_model(),
                db=self.db,
            )
        except Exception as e:
            logger.warning("Failed to create memory manager: %s", e)
            return None

    def _create_tool_event_hook(self) -> ToolEventHook:
        """Create a ToolEventHook for tool event hooks and protected path enforcement."""
        return ToolEventHook(
            executor=self.hook_executor,
            session_id=self.session_id,
            protected_paths=self.settings.safety.protected_paths,
            blocked_commands=self.settings.safety.blocked_commands,
        )

    # ── Lazy knowledge initialization (async, runs once) ──────────

    async def _ensure_knowledge(self) -> None:
        """Ensure knowledge is available (pre-loaded before Textual).

        Knowledge is loaded synchronously before the TUI starts to avoid
        fds_to_keep errors from SentenceTransformer subprocesses.  This
        method is a no-op if knowledge was pre-loaded successfully.
        """
        if self.knowledge is not None:
            return

        if not self.settings.knowledge.enabled:
            return

        # Knowledge was supposed to be pre-loaded but isn't available
        if not self._knowledge_error:
            self._knowledge_error = "Knowledge not available — embedder may have failed to load"

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
        self.main_team = self._build_main_agent()

    def rebuild_mcp(self) -> None:
        """Rebuild agents and main agent with current MCP client set.

        Called after toggling individual MCP servers on/off.
        """
        connected = self.mcp_manager.list_connected()
        clients = {name: self.mcp_manager._clients[name] for name in connected}
        self.pool.build_agents(mcp_clients=clients if clients else None)
        self.main_team = self._build_main_agent()

    # ── MCP status ─────────────────────────────────────────────────

    def get_mcp_status(self) -> list[tuple[str, bool]]:
        """Return list of (server_name, connected) for configured MCP servers."""
        available = set(self.mcp_manager.list_servers())
        connected = set(self.mcp_manager.list_connected())
        return [(name, name in connected) for name in available]

    # ── Dynamic context compaction ─────────────────────────────────

    async def _compact(self) -> None:
        """Generate a summary of the conversation, then clear old messages.

        1. Generate summary covering the full conversation
        2. Delete all runs from the session (summary preserved)
        3. Enable summary injection so the agent has context

        After compaction, messages accumulate fresh until next compaction.
        """
        # Load the session from DB
        agno_session = await self.main_team.aget_session(
            session_id=self.session_id,
            user_id=self.user_id,
        )
        if agno_session is None:
            logger.warning("No session found to compact")
            return

        # Create summary manager and generate summary
        try:
            from agno.session.summary import SessionSummaryManager

            ssm = SessionSummaryManager(model=self.main_team.model)
            await ssm.acreate_session_summary(session=agno_session)
            logger.info("Session summary generated")
        except Exception as e:
            logger.warning("Failed to generate session summary: %s", e)

        # Clear runs — summary stays
        agno_session.runs = []
        try:
            await self.main_team.asave_session(agno_session)
            logger.info("Session runs cleared from DB")
        except Exception as e:
            logger.warning("Failed to save session: %s", e)

        # Rebuild the main agent from scratch. This is the only reliable
        # way to clear Agno's in-memory message history — the cached
        # session, run_response, and internal state all hold old messages.
        self.main_team = self._build_main_agent()
        logger.info("Compacted: summary injected, agent rebuilt")

    async def compact_if_needed(self, input_tokens: int, context_window: int) -> bool:
        """Auto-compact at 80% context usage.

        Messages accumulate freely until context fills up. At 80%,
        a summary is generated and old turns are dropped.

        Returns True if compaction was applied.
        """
        if context_window <= 0 or input_tokens <= 0:
            return False

        usage = input_tokens / context_window
        if usage < 0.8:
            return False

        await self._compact()
        logger.info("Auto-compacted at %.0f%% context usage", usage * 100)
        return True

    async def force_compact(self) -> tuple[str, str]:
        """Manually compact conversation context.

        Returns (status_message, summary_text).
        """
        # Check if there's anything to compact
        try:
            agno_session = await self.main_team.aget_session(
                session_id=self.session_id,
                user_id=self.user_id,
            )
            if agno_session is None or not agno_session.runs:
                return "Nothing to compact — no conversation history.", ""
        except Exception:
            pass

        await self._compact()

        # Retrieve the generated summary from DB
        summary = ""
        try:
            agno_session = await self.main_team.aget_session(
                session_id=self.session_id,
                user_id=self.user_id,
            )
            if agno_session and agno_session.summary:
                summary = agno_session.summary.summary or ""
        except Exception:
            pass

        return "Context compacted. Conversation summarized, history cleared.", summary

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

    async def handle_message(self, message: str, **media_kwargs) -> str:
        """Handle a single user message and return the response.

        Accepts optional media keyword arguments (images, audio, videos, files)
        which are forwarded directly to team.arun().
        """

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
            from datetime import datetime

            timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
            effective_message = (
                f"<system-context>Current datetime: {timestamp}</system-context>\n{message}"
            )
            if guardrail_prefix:
                effective_message = guardrail_prefix + effective_message
            response = await self.main_team.arun(effective_message, stream=False, **media_kwargs)
            self._log_run_messages()
            response_text = extract_response_text(response)

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
                response = await self.main_team.arun(system_msg, stream=False)
                response_text = extract_response_text(response)

            # ── Compact history if approaching context limit ─────────
            metrics = getattr(getattr(self.main_team, "run_response", None), "metrics", None)
            if metrics:
                input_tokens = getattr(metrics, "input_tokens", 0) or 0
                await self.compact_if_needed(input_tokens, self._context_window)

            # ── Periodic memory extraction (background, every N turns) ─
            self._turn_count += 1
            self._recent_messages.append(message)
            if self._memory_manager is not None and self._turn_count % self._memory_interval == 0:
                from agno.models.message import Message as AgnoMessage

                batch = [AgnoMessage(role="user", content=m) for m in self._recent_messages]
                self._recent_messages.clear()
                asyncio.create_task(
                    self._memory_manager.acreate_user_memories(
                        messages=batch,
                        user_id=self.user_id,
                    )
                )

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
