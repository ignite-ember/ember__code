"""OrchestrateTools — allows agents to spawn sub-teams at runtime."""

import contextlib
import logging
import threading
import time
from typing import TYPE_CHECKING, Any

from agno.tools import Toolkit

if TYPE_CHECKING:
    from ember_code.core.config.settings import Settings
    from ember_code.core.hooks.executor import HookExecutor
    from ember_code.core.pool import AgentPool

logger = logging.getLogger(__name__)

_agent_counter_lock = threading.Lock()
_agent_counters: dict[str, int] = {}


def _format_args(tool_args: dict | None) -> str:
    if not tool_args:
        return ""
    parts = []
    for k, v in list(tool_args.items())[:2]:
        val = str(v).replace("\n", " ")
        if len(val) > 30:
            val = val[:27] + "..."
        parts.append(f"{k}={val}")
    return ", ".join(parts)


def _preview(result: Any, limit: int = 60) -> str:
    if result is None:
        return ""
    s = str(result).replace("\n", " ").strip()
    return s[:limit] + "..." if len(s) > limit else s


async def _run_agent_streaming(
    agent: Any, task: str, on_progress: Any = None
) -> tuple[str, list[str]]:
    """Stream an agent run, collecting activity log. Returns (response, log)."""
    from agno.run import agent as agent_events

    log: list[str] = []
    content: list[str] = []
    current_tool: str | None = None
    content_lines: list[str] = [""]  # sliding window of output lines
    last_update: float = 0.0
    last_preview: str = ""  # dedup: skip if same as last displayed

    def _log(line: str) -> None:
        log.append(line)
        if on_progress:
            with contextlib.suppress(Exception):
                on_progress(line)

    async for event in agent.arun(task, stream=True):
        if isinstance(event, agent_events.ToolCallStartedEvent):
            te = event.tool
            tn = (te.tool_name or "tool") if te else "tool"
            ta = te.tool_args if te else {}
            current_tool = tn
            _log(f"  │  ├─ {tn}({_format_args(ta)})")
        elif isinstance(event, agent_events.ToolCallCompletedEvent):
            te = event.tool
            r = getattr(te, "result", None) if te else None
            if current_tool:
                _log(f"  │  │  └─ {_preview(r)}")
                current_tool = None
        elif isinstance(event, agent_events.ToolCallErrorEvent):
            err = str(getattr(event, "error", "?"))
            _log(f"  │  │  └─ ERROR: {err[:60]}")
            current_tool = None
        elif isinstance(event, agent_events.RunContentEvent):
            c = event.content or ""
            if c:
                clean = c.replace("<think>", "").replace("</think>", "")
                if clean.strip():
                    # Detect cumulative vs delta content
                    accumulated = "".join(content)
                    if clean.startswith(accumulated) and len(clean) > len(accumulated):
                        clean = clean[len(accumulated) :]
                    content.append(clean)
                    # Build sliding window of output lines
                    for char in clean:
                        if char == "\n":
                            content_lines.append("")
                        else:
                            content_lines[-1] += char
                    now = time.monotonic()
                    if on_progress and now - last_update > 0.5:
                        last_update = now
                        current_line = content_lines[-1].strip() if content_lines else ""
                        if current_line and current_line != last_preview:
                            last_preview = current_line
                            preview = (
                                current_line[:120] + "..."
                                if len(current_line) > 120
                                else current_line
                            )
                            with contextlib.suppress(Exception):
                                on_progress(f"  │  ✎ {preview}")

    return "".join(content).strip(), log


async def _run_team_streaming(
    team: Any, task: str, on_progress: Any = None
) -> tuple[str, list[str]]:
    """Stream a team run, collecting activity log. Returns (response, log)."""
    from agno.run import agent as agent_events
    from agno.run import team as team_events

    log: list[str] = []
    content: list[str] = []
    current_tool: str | None = None
    current_agent: str = ""
    content_lines: list[str] = [""]
    last_update: float = 0.0
    last_preview: str = ""

    def _log(line: str) -> None:
        log.append(line)
        if on_progress:
            with contextlib.suppress(Exception):
                on_progress(line)

    async for event in team.arun(task, stream=True):
        if isinstance(event, team_events.TaskCreatedEvent):
            title = getattr(event, "title", "")
            assignee = getattr(event, "assignee", "")
            _log(f"  ┌─ TASK: {title}")
            if assignee:
                _log(f"  │  assigned to: {assignee}")
        elif isinstance(event, team_events.TaskUpdatedEvent):
            status = getattr(event, "status", "")
            icon = {"completed": "✓", "failed": "✗", "running": "…"}.get(status, "·")
            _log(f"  │  {icon} {status}")
        elif isinstance(event, team_events.TaskIterationStartedEvent):
            _log(f"  ╞═ Iteration {getattr(event, 'iteration', 0)}")
        elif isinstance(event, (agent_events.RunStartedEvent, team_events.RunStartedEvent)):
            name = getattr(event, "agent_name", None) or getattr(event, "team_name", None)
            if name and name != current_agent:
                current_agent = name
                _log(f"  ├─ [{name}]")
        elif isinstance(
            event, (agent_events.ToolCallStartedEvent, team_events.ToolCallStartedEvent)
        ):
            te = event.tool
            tn = (te.tool_name or "tool") if te else "tool"
            ta = te.tool_args if te else {}
            current_tool = tn
            _log(f"  │  ├─ {tn}({_format_args(ta)})")
        elif isinstance(
            event, (agent_events.ToolCallCompletedEvent, team_events.ToolCallCompletedEvent)
        ):
            te = event.tool
            r = getattr(te, "result", None) if te else None
            if current_tool:
                _log(f"  │  │  └─ {_preview(r)}")
                current_tool = None
        elif isinstance(event, (agent_events.ToolCallErrorEvent, team_events.ToolCallErrorEvent)):
            err = str(getattr(event, "error", "?"))
            _log(f"  │  │  └─ ERROR: {err[:60]}")
            current_tool = None
        elif isinstance(event, (agent_events.RunErrorEvent, team_events.RunErrorEvent)):
            err = str(getattr(event, "content", "?"))
            _log(f"  │  └─ ERROR: {err[:60]}")
        elif isinstance(event, (agent_events.RunContentEvent, team_events.RunContentEvent)):
            c = event.content or ""
            if c:
                clean = c.replace("<think>", "").replace("</think>", "")
                if clean.strip():
                    # Detect cumulative vs delta content
                    accumulated = "".join(content)
                    if clean.startswith(accumulated) and len(clean) > len(accumulated):
                        clean = clean[len(accumulated) :]
                    content.append(clean)
                    for char in clean:
                        if char == "\n":
                            content_lines.append("")
                        else:
                            content_lines[-1] += char
                    now = time.monotonic()
                    if on_progress and now - last_update > 0.5:
                        last_update = now
                        current_line = content_lines[-1].strip() if content_lines else ""
                        if current_line and current_line != last_preview:
                            last_preview = current_line
                            preview = (
                                current_line[:120] + "..."
                                if len(current_line) > 120
                                else current_line
                            )
                            with contextlib.suppress(Exception):
                                on_progress(f"  │  ✎ {preview}")

    return "".join(content).strip(), log


class OrchestrateTools(Toolkit):
    """Tools for agents to spawn sub-teams from the agent pool."""

    def __init__(
        self,
        pool: "AgentPool",
        settings: "Settings",
        current_depth: int = 0,
        hook_executor: "HookExecutor | None" = None,
        session_id: str = "",
    ):
        super().__init__(name="ember_orchestrate")
        self.pool = pool
        self.settings = settings
        self.current_depth = current_depth
        self.max_depth = settings.orchestration.max_nesting_depth
        self._hook_executor = hook_executor
        self._session_id = session_id
        self._max_agents = settings.orchestration.max_total_agents
        self._on_progress: Any = None
        self.register(self.spawn_agent)
        self.register(self.spawn_team)
        if settings.orchestration.generate_ephemeral:
            self.register(self.create_agent)

    def _check_agent_limit(self, count: int = 1) -> str | None:
        with _agent_counter_lock:
            current = _agent_counters.get(self._session_id, 0)
            if current + count > self._max_agents:
                return f"Error: Maximum total agents ({self._max_agents}) reached."
            _agent_counters[self._session_id] = current + count
            return None

    async def _fire_hook(self, event: str, extra: dict[str, Any] | None = None) -> None:
        if not self._hook_executor:
            return
        payload = {"session_id": self._session_id}
        if extra:
            payload.update(extra)
        with contextlib.suppress(Exception):
            await self._hook_executor.execute(event=event, payload=payload)

    async def spawn_agent(self, task: str, agent_name: str) -> str:
        """Run a single agent from the pool on a subtask.

        Args:
            task: The subtask description for the agent.
            agent_name: Name of the agent to spawn (from the pool).

        Returns:
            The agent's response with activity log.
        """
        if self.current_depth >= self.max_depth:
            return f"Error: Maximum nesting depth ({self.max_depth}) reached."

        if limit_err := self._check_agent_limit(1):
            return limit_err

        try:
            agent = self.pool.get(agent_name)
        except KeyError as e:
            return str(e)

        defn = self.pool.get_definition(agent_name)
        agent_desc = defn.description if defn else ""
        agent_tools = ", ".join(defn.tools) if defn and defn.tools else "none"

        await self._fire_hook("SubagentStart", {"agent_name": agent_name, "task": task[:500]})

        if self._on_progress:
            with contextlib.suppress(Exception):
                self._on_progress(f"  ├─ [{agent_name}]")

        try:
            start = time.monotonic()
            result, activity = await _run_agent_streaming(
                agent, task, on_progress=self._on_progress
            )
            elapsed = time.monotonic() - start

            await self._fire_hook(
                "SubagentStop", {"agent_name": agent_name, "result_preview": result[:500]}
            )

            activity_log = "\n".join(activity) if activity else "  (no tool calls)"
            return (
                f"[Agent: {agent_name}] {agent_desc}\n"
                f"[Tools: {agent_tools}]\n"
                f"[Task: {task}]\n"
                f"[Time: {elapsed:.1f}s]\n\n"
                f"Activity:\n{activity_log}\n\n"
                f"Response:\n{result}"
            )
        except Exception as e:
            error = f"Error running sub-agent '{agent_name}': {e}"
            await self._fire_hook("SubagentStop", {"agent_name": agent_name, "error": error})
            return error

    async def spawn_team(self, task: str, agent_names: str, mode: str = "coordinate") -> str:
        """Create and run a sub-team for a specific subtask.

        Args:
            task: The subtask description.
            agent_names: Comma-separated agent names from the pool.
            mode: Team mode: "coordinate", "route", "broadcast", or "tasks".

        Returns:
            The team's response with activity log.
        """
        if self.current_depth >= self.max_depth:
            return f"Error: Maximum nesting depth ({self.max_depth}) reached."

        names = [n.strip() for n in agent_names.split(",") if n.strip()]
        if limit_err := self._check_agent_limit(len(names)):
            return limit_err
        if not names:
            return "Error: No agent names provided."
        if len(names) == 1:
            return await self.spawn_agent(task, names[0])

        try:
            from agno.team.team import Team

            from ember_code.core.config.models import ModelRegistry

            members = []
            for name in names:
                try:
                    members.append(self.pool.get(name))
                except KeyError as e:
                    return str(e)

            valid_modes = ("route", "coordinate", "broadcast", "tasks")
            if mode not in valid_modes:
                mode = "coordinate"

            team_model = ModelRegistry(self.settings).get_model()
            team_kwargs: dict[str, Any] = {
                "name": f"sub-team-depth-{self.current_depth + 1}",
                "mode": mode,
                "model": team_model,
                "members": members,
                "markdown": True,
            }
            if mode == "tasks":
                team_kwargs["max_iterations"] = self.settings.orchestration.max_task_iterations

            team = Team(**team_kwargs)

            member_lines = []
            for n in names:
                defn = self.pool.get_definition(n)
                desc = defn.description[:60] if defn else ""
                member_lines.append(f"  - {n}: {desc}")

            await self._fire_hook(
                "SubagentStart",
                {"agent_name": f"team({','.join(names)})", "task": task[:500], "mode": mode},
            )

            start = time.monotonic()
            result, activity = await _run_team_streaming(team, task, on_progress=self._on_progress)
            elapsed = time.monotonic() - start

            await self._fire_hook(
                "SubagentStop",
                {"agent_name": f"team({','.join(names)})", "result_preview": result[:500]},
            )

            activity_log = "\n".join(activity) if activity else "  (no activity)"
            return (
                f"[Team: {', '.join(names)}] (mode: {mode})\n"
                f"[Members:\n" + "\n".join(member_lines) + "]\n"
                f"[Task: {task}]\n"
                f"[Time: {elapsed:.1f}s]\n\n"
                f"Activity:\n{activity_log}\n\n"
                f"Response:\n{result}"
            )
        except Exception as e:
            error = f"Error running sub-team: {e}"
            await self._fire_hook(
                "SubagentStop", {"agent_name": f"team({','.join(names)})", "error": error}
            )
            return error

    def create_agent(
        self,
        name: str,
        description: str,
        system_prompt: str,
        tools: str = "Read,Write,Edit,Bash,Grep,Glob",
    ) -> str:
        """Create a new ephemeral agent with a custom system prompt.

        Args:
            name: Short snake_case name for the agent.
            description: One-line description of what the agent does.
            system_prompt: Full system prompt defining the agent's behavior.
            tools: Comma-separated tool names (e.g. "Read,Write,Edit,Bash,Grep,Glob").
                Valid: Read, Write, Edit, Bash, Grep, Glob, LS, WebSearch, WebFetch,
                Python, Schedule, NotebookEdit.

        Returns:
            Confirmation message with the agent name.
        """
        tool_list = [t.strip() for t in tools.split(",") if t.strip()]
        try:
            self.pool.register_ephemeral(
                name=name, description=description, system_prompt=system_prompt, tools=tool_list
            )
            return f"Created ephemeral agent '{name}': {description}. Use spawn_agent(task, '{name}') to delegate."
        except (ValueError, RuntimeError) as e:
            return f"Error creating agent: {e}"


def reset_agent_counter(session_id: str) -> None:
    with _agent_counter_lock:
        _agent_counters.pop(session_id, None)
