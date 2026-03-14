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

    async def _cmd_help(self, _args: str) -> "CommandResult":
        skills_text = ""
        for s in self._session.skill_pool.list_skills():
            hint = f" {s.argument_hint}" if s.argument_hint else ""
            skills_text += f"- **/{s.name}**{hint} — {s.description[:60]}\n"

        return CommandResult.markdown(
            "## Commands\n"
            "- `/help` — show this help\n"
            "- `/quit` — exit\n"
            "- `/agents` — list loaded agents\n"
            "- `/skills` — list loaded skills\n"
            "- `/hooks` — list loaded hooks\n"
            "- `/clear` — reset conversation context\n"
            "- `/sessions` — browse and resume past sessions\n"
            "- `/rename <name>` — rename the current session\n"
            "- `/memory` — list stored memories\n"
            "- `/memory optimize` — consolidate memories\n"
            "- `/config` — show current settings\n"
            "\n## Skills\n"
            f"{skills_text or '(no skills loaded)'}\n"
            f"\n{SHORTCUT_HELP}"
        )

    async def _cmd_agents(self, _args: str) -> "CommandResult":
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

    async def _cmd_hooks(self, _args: str) -> "CommandResult":
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

        # Default: list memories
        memories = await self._session.memory_mgr.get_memories()
        if not memories:
            return CommandResult.info("No memories stored yet.")

        lines = f"## Memories ({len(memories)})\n"
        for i, m in enumerate(memories, 1):
            lines += f"{i}. {m['memory']}\n"
            if m["topics"]:
                lines += f"   [dim]topics: {m['topics']}[/dim]\n"
        lines += "\n[dim]Use `/memory optimize` to consolidate memories.[/dim]\n"
        return CommandResult.markdown(lines)

    async def _cmd_knowledge(self, args: str) -> "CommandResult":
        """Handle /knowledge commands: add url|path|text, search, status."""
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

    async def _cmd_config(self, _args: str) -> "CommandResult":
        s = self._session.settings
        return CommandResult.markdown(
            "## Configuration\n"
            f"- **Model:** {s.models.default}\n"
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

    async def _handle_skill(self, stripped: str) -> "CommandResult":
        """Try to match and execute a skill command."""
        skill_match = self._session.skill_pool.match_user_command(stripped)
        if skill_match:
            skill, args = skill_match
            from ember_code.skills.executor import execute_skill

            result = await execute_skill(skill, args, self._session.pool, self._session.settings)
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
    }
