"""Command handler — processes slash commands for the TUI."""

from typing import TYPE_CHECKING, Any

from ember_code.tui.input_handler import SHORTCUT_HELP

if TYPE_CHECKING:
    from ember_code.session import Session


class CommandResult:
    """Result of executing a slash command."""

    def __init__(
        self,
        kind: str = "markdown",
        content: str = "",
        action: str | None = None,
    ):
        self.kind = kind  # "markdown", "info", "error", "action"
        self.content = content
        self.action = action  # "quit", "clear", None

    @classmethod
    def markdown(cls, text: str) -> "CommandResult":
        return cls(kind="markdown", content=text)

    @classmethod
    def info(cls, text: str) -> "CommandResult":
        return cls(kind="info", content=text)

    @classmethod
    def error(cls, text: str) -> "CommandResult":
        return cls(kind="error", content=text)

    @classmethod
    def quit(cls) -> "CommandResult":
        return cls(kind="action", action="quit")

    @classmethod
    def clear(cls) -> "CommandResult":
        return cls(kind="action", action="clear")

    @classmethod
    def sessions(cls) -> "CommandResult":
        return cls(kind="action", action="sessions")

    @classmethod
    def model(cls) -> "CommandResult":
        return cls(kind="action", action="model")

    @classmethod
    def login(cls) -> "CommandResult":
        return cls(kind="action", action="login")

    @classmethod
    def mcp(cls) -> "CommandResult":
        return cls(kind="action", action="mcp")


class CommandHandler:
    """Handles slash commands, decoupled from the TUI rendering.

    Each command returns a ``CommandResult`` that the app renders
    appropriately.
    """

    def __init__(self, session: "Session"):
        self._session = session

    async def handle(self, command: str) -> "CommandResult":
        """Dispatch a slash command and return its result."""
        stripped = command.strip()
        cmd = stripped.split()[0].lower()
        args = stripped[len(cmd) :].strip()

        handler = self._COMMANDS.get(cmd)
        if handler:
            return await handler(self, args)

        # Try skill match
        return await self._handle_skill(stripped)

    # ── Commands ──────────────────────────────────────────────────

    async def _cmd_quit(self, _args: str) -> "CommandResult":
        return CommandResult.quit()

    _HELP_TOPICS: dict[str, str] = {
        "schedule": (
            "## Schedule\n\n"
            "Schedule tasks for later or recurring execution.\n\n"
            "**Commands:**\n"
            "- `/schedule` — list pending tasks\n"
            "- `/schedule all` — include completed and cancelled\n"
            "- `/schedule add <description> at <time>` — one-shot task\n"
            "- `/schedule add <description> in <duration>` — relative time\n"
            "- `/schedule add <description> every <interval>` — recurring\n"
            "- `/schedule show <id>` — show task details\n"
            "- `/schedule cancel <id>` — cancel a task\n\n"
            "**Time formats:**\n"
            "- One-shot: `at 5pm`, `at 3:30`, `tomorrow`, `tomorrow at 9am`, `2026-12-25 14:00`\n"
            "- Relative: `in 30 minutes`, `in 2 hours`, `in 1 day`\n"
            "- Recurring: `every 2 hours`, `every 30 minutes`, `daily`, `daily at 9am`, `hourly`, `weekly`\n\n"
            "**Examples:**\n"
            "```\n"
            "/schedule add review code at 5pm\n"
            "/schedule add run tests in 30 minutes\n"
            "/schedule add check deps daily\n"
            "/schedule add run linter every 2 hours\n"
            "```"
        ),
        "agents": (
            "## Agents\n\n"
            "Agents are specialist roles with tools and system prompts.\n\n"
            "**Commands:**\n"
            "- `/agents` — list all loaded agents with tools\n"
            "- `/agents ephemeral` — list dynamically created agents\n"
            "- `/agents promote <name>` — save ephemeral agent permanently\n"
            "- `/agents discard <name>` — delete an ephemeral agent\n\n"
            "**Create agents:** add `.md` files to `.ember/agents/`\n"
            "**Customize:** edit any agent in `.ember/agents/` to change its behavior"
        ),
        "knowledge": (
            "## Knowledge Base\n\n"
            "Store and search project knowledge with embeddings.\n\n"
            "**Commands:**\n"
            "- `/knowledge` — show status (collection, doc count, embedder)\n"
            "- `/knowledge add <url>` — add a URL\n"
            "- `/knowledge add <path>` — add a file or directory\n"
            "- `/knowledge add <text>` — add inline text\n"
            "- `/knowledge search <query>` — search the knowledge base\n"
            "- `/sync-knowledge` — sync between git file and vector DB"
        ),
        "memory": (
            "## Memory & Learning\n\n"
            "Ember Code learns your preferences automatically from conversations.\n\n"
            "**Commands:**\n"
            "- `/memory` — show what Ember has learned about you\n"
            "- `/memory optimize` — consolidate memories\n\n"
            "**What gets learned:**\n"
            "- Your name and how you prefer to be addressed\n"
            "- Tool and framework preferences (pytest, ruff, Pydantic, etc.)\n"
            "- Project structure conventions (src/ layout, etc.)\n"
            "- Coding style preferences (type hints, etc.)\n\n"
            "Learning happens in the background after each response."
        ),
        "mcp": (
            "## MCP Servers\n\n"
            "Connect external tools via the Model Context Protocol.\n\n"
            "**Commands:**\n"
            "- `/mcp` — open the MCP panel (browse, connect, disconnect)\n\n"
            "**Configuration:** add servers to `.mcp.json`:\n"
            "```json\n"
            '{"mcpServers": {"name": {"type": "stdio", "command": "npx", "args": [...]}}}\n'
            "```\n"
            "**Transports:** `stdio` and `sse` supported\n"
            "**Panel controls:** Space toggle, Enter expand tools, Escape close"
        ),
        "shortcuts": SHORTCUT_HELP,
    }

    async def _cmd_help(self, args: str) -> "CommandResult":
        topic = args.strip().lower()

        # Topic-specific help
        if topic and topic in self._HELP_TOPICS:
            return CommandResult.markdown(self._HELP_TOPICS[topic])

        # List available topics if unknown
        if topic:
            available = ", ".join(sorted(self._HELP_TOPICS.keys()))
            return CommandResult.error(f"Unknown help topic: {topic}. Available: {available}")

        # No topic: show interactive panel
        return CommandResult(kind="info", content="", action="help")

    async def _cmd_agents(self, args: str) -> "CommandResult":
        parts = args.strip().split(None, 1)
        subcommand = parts[0].lower() if parts else ""
        sub_args = parts[1].strip() if len(parts) > 1 else ""

        if subcommand == "promote" and sub_args:
            name = sub_args.strip()
            try:
                dest = self._session.pool.promote_ephemeral(name, self._session.project_dir)
                return CommandResult.info(f"Promoted '{name}' to {dest}")
            except (KeyError, ValueError, RuntimeError) as e:
                return CommandResult.error(str(e))

        if subcommand == "discard" and sub_args:
            name = sub_args.strip()
            try:
                self._session.pool.discard_ephemeral(name)
                return CommandResult.info(f"Discarded ephemeral agent '{name}'.")
            except (KeyError, ValueError, RuntimeError) as e:
                return CommandResult.error(str(e))

        if subcommand == "ephemeral":
            agents = self._session.pool.list_ephemeral()
            if not agents:
                return CommandResult.info("No ephemeral agents.")
            lines = "## Ephemeral Agents\n"
            for defn in agents:
                tools = ", ".join(defn.tools) if defn.tools else "none"
                lines += f"- **{defn.name}** — {defn.description}\n  tools: {tools}\n"
            lines += "\n*Use `/agents promote <name>` to make permanent.*\n"
            return CommandResult.markdown(lines)

        # Default: list all agents
        lines = "## Agents\n"
        for defn in self._session.pool.list_agents():
            tools = ", ".join(defn.tools) if defn.tools else "none"
            lines += f"- **{defn.name}** — {defn.description}\n  tools: {tools}\n"
        return CommandResult.markdown(lines)

    async def _cmd_skills(self, _args: str) -> "CommandResult":
        lines = "## Skills\n"
        for skill in self._session.skill_pool.list_skills():
            hint = f" {skill.argument_hint}" if skill.argument_hint else ""
            lines += f"- **/{skill.name}**{hint} — {skill.description}\n"
        return CommandResult.markdown(lines or "## Skills\n(no skills loaded)")

    async def _cmd_hooks(self, args: str) -> "CommandResult":
        subcommand = args.strip().lower()
        if subcommand == "reload":
            count = self._session.reload_hooks()
            return CommandResult.info(f"Hooks reloaded. {count} hook(s) loaded.")

        if not self._session.hooks_map:
            return CommandResult.info("No hooks loaded.")
        lines = "## Hooks\n"
        for event, hook_list in self._session.hooks_map.items():
            for h in hook_list:
                matcher = f" (matcher: {h.matcher})" if h.matcher else ""
                lines += f"- **{event}**: `{h.command or h.url}`{matcher}\n"
        return CommandResult.markdown(lines)

    async def _cmd_clear(self, _args: str) -> "CommandResult":
        # Generate new session_id so Agno starts fresh history
        import uuid

        self._session.session_id = str(uuid.uuid4())[:8]
        return CommandResult.clear()

    async def _cmd_sessions(self, _args: str) -> "CommandResult":
        return CommandResult.sessions()

    async def _cmd_rename(self, args: str) -> "CommandResult":
        name = args.strip()
        if not name:
            return CommandResult.error("Usage: /rename <new session name>")
        await self._session.persistence.rename(name)
        return CommandResult.info(f"Session renamed to: {name}")

    async def _cmd_memory(self, args: str) -> "CommandResult":
        subcommand = args.strip().lower()

        if subcommand == "optimize":
            result = await self._session.memory_mgr.optimize()
            if "error" in result:
                return CommandResult.error(f"Memory optimization failed: {result['error']}")
            return CommandResult.info(result["message"])

        # Show Learning Machine data — use agent's property which triggers lazy init
        learning = getattr(self._session.main_team, "learning_machine", None)
        if learning is None:
            learning = getattr(self._session, "_learning", None)
        if learning is None:
            return CommandResult.info(
                "Learning is not enabled. Set learning.enabled=true in config."
            )

        sections: list[str] = []
        try:
            # Recall with session_id=None to get cross-session data
            # (user profile, user memory, entity memory)
            data = await learning.arecall(
                user_id=self._session.user_id,
            )
            for store_name, store_data in data.items():
                if not store_data:
                    continue
                title = store_name.replace("_", " ").title()
                lines = f"## {title}\n"

                if store_name == "user_profile":
                    for attr in ("name", "preferred_name", "role", "expertise", "preferences"):
                        val = getattr(store_data, attr, None)
                        if val:
                            lines += f"- **{attr.replace('_', ' ').title()}**: {val}\n"

                elif store_name == "user_memory":
                    memories = getattr(store_data, "memories", []) or []
                    for m in memories:
                        content = m.get("content", "") if isinstance(m, dict) else str(m)
                        if content:
                            lines += f"- {content}\n"

                elif store_name == "session_context":
                    summary = getattr(store_data, "summary", None)
                    if summary:
                        lines += f"{summary}\n"

                elif store_name == "entity_memory":
                    entities = getattr(store_data, "entities", []) or []
                    for e in entities:
                        if isinstance(e, dict):
                            lines += f"- **{e.get('name', '?')}**: {e.get('description', '')}\n"
                        else:
                            lines += f"- {e}\n"

                else:
                    lines += f"{store_data}\n"

                if lines.strip() != f"## {title}":
                    sections.append(lines)
        except Exception:
            pass

        if not sections:
            return CommandResult.info(
                "No learnings stored yet. The agent learns from your conversations automatically."
            )

        return CommandResult.markdown("\n\n".join(sections))

    async def _cmd_knowledge(self, args: str) -> "CommandResult":
        """Handle /knowledge commands: add url|path|text, search, status."""
        # Ensure knowledge is loaded (deferred from startup)
        await self._session._ensure_knowledge()

        parts = args.strip().split(None, 1)
        subcommand = parts[0].lower() if parts else ""
        sub_args = parts[1].strip() if len(parts) > 1 else ""

        if subcommand == "add" and sub_args:
            # Detect if it's a URL, path, or text
            if sub_args.startswith("http://") or sub_args.startswith("https://"):
                result = await self._session.knowledge_mgr.add(url=sub_args)
            elif "/" in sub_args or sub_args.startswith("."):
                result = await self._session.knowledge_mgr.add(path=sub_args)
            else:
                result = await self._session.knowledge_mgr.add(text=sub_args)

            if not result.success:
                return CommandResult.error(result.error)
            return CommandResult.info(result.message)

        if subcommand == "search" and sub_args:
            response = await self._session.knowledge_mgr.search(sub_args)
            if not response.results:
                return CommandResult.info("No results found.")
            lines = f"## Knowledge Search ({response.total} results)\n"
            for i, r in enumerate(response.results, 1):
                name = r.name or "untitled"
                lines += f"\n**{i}. {name}**\n{r.content}\n"
            return CommandResult.markdown(lines)

        # Default: status
        status = self._session.knowledge_mgr.status()
        if not status.enabled:
            if self._session.settings.knowledge.enabled:
                if self._session._knowledge_error:
                    return CommandResult.error(
                        f"Knowledge failed to load: {self._session._knowledge_error}"
                    )
                if self._session._knowledge_loading and not (
                    self._session._knowledge_event and self._session._knowledge_event.is_set()
                ):
                    return CommandResult.info("Knowledge base is loading... Try again in a moment.")
                return CommandResult.error("Knowledge base failed to initialize.")
            return CommandResult.info(
                "Knowledge base is disabled. Set knowledge.enabled=true in config."
            )
        return CommandResult.markdown(
            "## Knowledge Base\n"
            f"- **Status:** enabled\n"
            f"- **Collection:** {status.collection_name}\n"
            f"- **Documents:** {status.document_count}\n"
            f"- **Embedder:** {status.embedder}\n"
            "\n**Commands:**\n"
            "- `/knowledge add <url>` — add a URL\n"
            "- `/knowledge add <path>` — add a file/directory\n"
            "- `/knowledge add <text>` — add inline text\n"
            "- `/knowledge search <query>` — search the knowledge base\n"
        )

    async def _cmd_model(self, args: str) -> "CommandResult":
        name = args.strip()
        if name:
            # Direct switch: /model gemini-2.5-flash
            registry = self._session.settings.models.registry
            if name not in registry:
                available = ", ".join(sorted(registry.keys()))
                return CommandResult.error(f"Unknown model: '{name}'. Available: {available}")
            self._session.settings.models.default = name
            self._session.main_team = self._session._build_main_agent()
            return CommandResult.info(f"Switched to model: {name}")
        # No args: show picker
        return CommandResult.model()

    async def _cmd_config(self, _args: str) -> "CommandResult":
        s = self._session.settings

        # Auth status line
        from ember_code.auth.credentials import is_token_expired, load_credentials

        creds = load_credentials()
        if creds and not is_token_expired(creds):
            auth_status = creds.email or "logged in"
        else:
            auth_status = "not logged in"

        return CommandResult.markdown(
            "## Configuration\n"
            f"- **Model:** {s.models.default}\n"
            f"- **Auth:** {auth_status}\n"
            f"- **Permissions:** file_write={s.permissions.file_write}, "
            f"shell={s.permissions.shell_execute}\n"
            f"- **Storage:** {s.storage.backend}\n"
            f"- **Agentic memory:** {'enabled' if s.memory.enable_agentic_memory else 'disabled'}\n"
            f"- **Learning:** {'enabled' if s.learning.enabled else 'disabled'}\n"
            f"- **Reasoning tools:** {'enabled' if s.reasoning.enabled else 'disabled'}\n"
            f"- **Guardrails:** "
            f"{'PII ' if s.guardrails.pii_detection else ''}"
            f"{'injection ' if s.guardrails.prompt_injection else ''}"
            f"{'moderation ' if s.guardrails.moderation else ''}"
            f"{'(none)' if not any([s.guardrails.pii_detection, s.guardrails.prompt_injection, s.guardrails.moderation]) else ''}\n"
            f"- **Knowledge:** {'enabled (' + s.knowledge.embedder + ')' if s.knowledge.enabled else 'disabled'}\n"
            f"- **Compression:** enabled\n"
            f"- **Session summaries:** enabled\n"
            f"- **Max agents:** {s.orchestration.max_total_agents}\n"
            f"- **Max depth:** {s.orchestration.max_nesting_depth}\n"
            f"- **Session:** {self._session.session_id}\n"
        )

    async def _cmd_mcp(self, _args: str) -> "CommandResult":
        return CommandResult.mcp()

    async def _cmd_login(self, _args: str) -> "CommandResult":
        return CommandResult.login()

    async def _cmd_logout(self, _args: str) -> "CommandResult":
        from ember_code.auth.credentials import clear_credentials, load_credentials

        creds = load_credentials()
        clear_credentials()

        # Clear in-memory cloud state and rebuild agent with direct model URL
        if self._session:
            self._session._cloud_token = None
            self._session._cloud_org_id = None
            self._session._cloud_org_name = None
            self._session.main_team = self._session._build_main_agent()

        msg = f"Logged out ({creds.email})." if creds else "Not logged in."
        return CommandResult(kind="info", content=msg, action="logout")

    async def _cmd_whoami(self, _args: str) -> "CommandResult":
        from ember_code.auth.credentials import is_token_expired, load_credentials

        creds = load_credentials()
        if creds is None:
            return CommandResult.info("Not logged in. Use /login to authenticate.")
        if is_token_expired(creds):
            return CommandResult.info(
                f"Session expired for {creds.email}. Use /login to re-authenticate."
            )
        expires = creds.expires_at[:19] if creds.expires_at else "unknown"
        return CommandResult.info(f"Logged in as {creds.email} (expires: {expires})")

    async def _cmd_schedule(self, args: str) -> "CommandResult":
        """Handle /schedule commands: add, list, remove, show."""

        from ember_code.scheduler.models import TaskStatus
        from ember_code.scheduler.store import TaskStore

        store = TaskStore()
        parts = args.strip().split(None, 1)
        subcommand = parts[0].lower() if parts else "list"
        sub_args = parts[1].strip() if len(parts) > 1 else ""

        if subcommand == "add" and sub_args:
            return await self._schedule_add(store, sub_args)

        if subcommand in ("rm", "remove", "cancel") and sub_args:
            task_id = sub_args.strip()
            task = await store.get(task_id)
            if not task:
                return CommandResult.error(f"Task not found: {task_id}")
            if task.status in (TaskStatus.pending, TaskStatus.running):
                await store.update_status(task_id, TaskStatus.cancelled)
                return CommandResult.info(f"Cancelled task {task_id}")
            return CommandResult.info(f"Task {task_id} is already {task.status.value}")

        if subcommand == "show" and sub_args:
            task = await store.get(sub_args.strip())
            if not task:
                return CommandResult.error(f"Task not found: {sub_args.strip()}")
            lines = (
                f"## Task {task.id}\n"
                f"- **Description:** {task.description}\n"
                f"- **Scheduled:** {task.scheduled_at.strftime('%Y-%m-%d %H:%M')}\n"
                f"- **Status:** {task.status.value}\n"
                f"- **Created:** {task.created_at.strftime('%Y-%m-%d %H:%M')}\n"
            )
            if task.result:
                lines += f"\n**Result:**\n{task.result}\n"
            if task.error:
                lines += f"\n**Error:**\n{task.error}\n"
            return CommandResult.markdown(lines)

        if subcommand == "all":
            tasks = await store.get_all(include_done=True)
        else:
            # Default: list pending/running
            tasks = await store.get_all(include_done=False)

        if not tasks:
            return CommandResult.info("No scheduled tasks.")

        lines = "## Scheduled Tasks\n"
        for t in tasks:
            time_str = t.scheduled_at.strftime("%Y-%m-%d %H:%M")
            status_icon = {
                "pending": "pending",
                "running": "**running**",
                "completed": "done",
                "failed": "FAILED",
                "cancelled": "cancelled",
            }.get(t.status.value, t.status.value)
            desc = t.description[:60] + ("..." if len(t.description) > 60 else "")
            lines += f"- `{t.id}` {status_icon} {time_str} — {desc}\n"
        lines += "\n*Use `/schedule show <id>` for details, `/schedule cancel <id>` to cancel.*\n"
        return CommandResult.markdown(lines)

    @staticmethod
    async def _schedule_add(store, text: str) -> "CommandResult":
        """Parse 'description at/in/every time' and create a task."""
        import uuid

        from ember_code.scheduler.models import ScheduledTask
        from ember_code.scheduler.parser import parse_recurrence, parse_time

        # Try recurring: "run tests every 2 hours", "check deps daily", "audit weekly at 9am"
        for sep in (" every ", " daily", " hourly", " weekly"):
            idx = text.lower().rfind(sep)
            if idx > 0:
                description = text[:idx].strip()
                recur_part = text[idx:].strip()
                recurrence, scheduled = parse_recurrence(recur_part)
                if recurrence and scheduled:
                    task = ScheduledTask(
                        id=uuid.uuid4().hex[:8],
                        description=description,
                        scheduled_at=scheduled,
                        recurrence=recurrence,
                    )
                    await store.add(task)
                    return CommandResult.info(
                        f'Scheduled `{task.id}`: "{description}" '
                        f"({recurrence}, first at {scheduled.strftime('%Y-%m-%d %H:%M')})"
                    )

        # Try one-shot: "review codebase at 5pm"
        for sep in (" at ", " in ", " on ", " tomorrow"):
            idx = text.lower().rfind(sep)
            if idx > 0:
                description = text[:idx].strip()
                time_part = text[idx:].strip()
                scheduled = parse_time(time_part)
                if scheduled:
                    task = ScheduledTask(
                        id=uuid.uuid4().hex[:8],
                        description=description,
                        scheduled_at=scheduled,
                    )
                    await store.add(task)
                    return CommandResult.info(
                        f'Scheduled `{task.id}`: "{description}" at {scheduled.strftime("%Y-%m-%d %H:%M")}'
                    )

        return CommandResult.error(
            "Could not parse time. Examples:\n"
            "  /schedule add review the codebase at 5pm\n"
            "  /schedule add run tests in 30 minutes\n"
            "  /schedule add audit security tomorrow\n"
            "  /schedule add run tests every 2 hours\n"
            "  /schedule add check dependencies daily"
        )

    async def _cmd_evals(self, args: str) -> "CommandResult":
        from ember_code.evals.reporter import format_results
        from ember_code.evals.runner import SuiteResult

        agent_filter = args.strip() or None

        results = await SuiteResult.run_all(
            pool=self._session.pool,
            settings=self._session.settings,
            project_dir=self._session.project_dir,
            agent_filter=agent_filter,
        )

        if not results:
            return CommandResult.info("No eval suites found. Add YAML files to .ember/evals/")
        return CommandResult.markdown(format_results(results))

    async def _cmd_sync_knowledge(self, _args: str) -> "CommandResult":
        await self._session._ensure_knowledge()
        if not self._session.knowledge_mgr.share_enabled():
            return CommandResult.info(
                "Knowledge sharing is not enabled. Set knowledge.share=true in config."
            )
        results = await self._session.knowledge_mgr.sync_bidirectional()
        lines = [f"[{r.direction}] {r.summary}" for r in results]
        return CommandResult.info("\n".join(lines))

    async def _cmd_compact(self, _args: str) -> "CommandResult":
        _, summary = await self._session.force_compact()
        if not summary:
            return CommandResult(kind="action", action="noop")
        return CommandResult(kind="action", action="compact", content=summary)

    async def _cmd_bug(self, _args: str) -> "CommandResult":
        import webbrowser

        url = "https://github.com/vector-bridge/ember__code/issues"
        webbrowser.open(url)
        return CommandResult.info(f"Opened {url}")

    async def _handle_skill(self, stripped: str) -> "CommandResult":
        """Try to match and execute a skill command."""
        skill_match = self._session.skill_pool.match_user_command(stripped)
        if skill_match:
            skill, args = skill_match
            from ember_code.skills.executor import SkillExecutor

            result = await SkillExecutor(
                self._session.pool, self._session.settings, self._session.session_id
            ).execute(skill, args)
            return CommandResult.markdown(result)
        return CommandResult.error(f"Unknown command: {stripped.split()[0]}")

    # ── Command dispatch table ────────────────────────────────────

    _COMMANDS: dict[str, Any] = {
        "/quit": _cmd_quit,
        "/exit": _cmd_quit,
        "/help": _cmd_help,
        "/agents": _cmd_agents,
        "/skills": _cmd_skills,
        "/hooks": _cmd_hooks,
        "/clear": _cmd_clear,
        "/sessions": _cmd_sessions,
        "/rename": _cmd_rename,
        "/memory": _cmd_memory,
        "/knowledge": _cmd_knowledge,
        "/config": _cmd_config,
        "/model": _cmd_model,
        "/mcp": _cmd_mcp,
        "/login": _cmd_login,
        "/logout": _cmd_logout,
        "/whoami": _cmd_whoami,
        "/schedule": _cmd_schedule,
        "/compact": _cmd_compact,
        "/bug": _cmd_bug,
        "/evals": _cmd_evals,
        "/sync-knowledge": _cmd_sync_knowledge,
    }
