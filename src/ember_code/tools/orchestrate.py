"""OrchestrateTools — allows agents to spawn sub-teams at runtime."""

import logging
import threading
from typing import TYPE_CHECKING, Any

from agno.tools import Toolkit

if TYPE_CHECKING:
    from ember_code.config.settings import Settings
    from ember_code.hooks.executor import HookExecutor
    from ember_code.pool import AgentPool

logger = logging.getLogger(__name__)

# Session-level counter for total spawned agents (shared across all OrchestrateTools instances)
_agent_counter_lock = threading.Lock()
_agent_counters: dict[str, int] = {}  # session_id -> count


class OrchestrateTools(Toolkit):
    """Tools for agents to spawn sub-teams from the agent pool.

    Enables unlimited nesting: any agent with this toolkit can spawn
    sub-teams or individual agents to handle subtasks.
    """

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
        self.register(self.spawn_agent)
        self.register(self.spawn_team)
        if settings.orchestration.generate_ephemeral:
            self.register(self.create_agent)

    def _check_agent_limit(self, count: int = 1) -> str | None:
        """Check if spawning ``count`` more agents would exceed the session limit.

        Returns an error message if the limit would be exceeded, or None if OK.
        """
        with _agent_counter_lock:
            current = _agent_counters.get(self._session_id, 0)
            if current + count > self._max_agents:
                return (
                    f"Error: Maximum total agents ({self._max_agents}) reached for this session. "
                    f"Complete this task with the agents already running."
                )
            _agent_counters[self._session_id] = current + count
            return None

    def _fire_hook(self, event: str, extra: dict[str, Any] | None = None) -> None:
        """Fire a hook event if executor is available. Best-effort, never raises."""
        if not self._hook_executor:
            return
        payload = {"session_id": self._session_id}
        if extra:
            payload.update(extra)
        try:
            import asyncio

            asyncio.run(self._hook_executor.execute(event=event, payload=payload))
        except Exception:
            logger.debug("Hook %s failed (non-fatal)", event, exc_info=True)

    def spawn_agent(self, task: str, agent_name: str) -> str:
        """Run a single agent from the pool on a subtask.

        Args:
            task: The subtask description for the agent.
            agent_name: Name of the agent to spawn (from the pool).

        Returns:
            The agent's response.
        """
        if self.current_depth >= self.max_depth:
            return (
                f"Error: Maximum nesting depth ({self.max_depth}) reached. "
                f"Complete this task without spawning sub-agents."
            )

        if limit_err := self._check_agent_limit(1):
            return limit_err

        try:
            agent = self.pool.get(agent_name)
        except KeyError as e:
            return str(e)

        self._fire_hook("SubagentStart", {"agent_name": agent_name, "task": task[:500]})

        try:
            import asyncio

            async def _run():
                response = await agent.arun(task)
                if hasattr(response, "content"):
                    return str(response.content)
                return str(response)

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures

                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(asyncio.run, _run())
                        result = future.result(timeout=self.settings.orchestration.sub_team_timeout)
                else:
                    result = loop.run_until_complete(_run())
            except RuntimeError:
                result = asyncio.run(_run())

            self._fire_hook(
                "SubagentStop", {"agent_name": agent_name, "result_preview": result[:500]}
            )
            return result
        except TimeoutError:
            error = f"Error: Sub-agent '{agent_name}' timed out after {self.settings.orchestration.sub_team_timeout}s."
            self._fire_hook("SubagentStop", {"agent_name": agent_name, "error": error})
            return error
        except Exception as e:
            error = f"Error running sub-agent '{agent_name}': {e}"
            self._fire_hook("SubagentStop", {"agent_name": agent_name, "error": error})
            return error

    def spawn_team(
        self,
        task: str,
        agent_names: str,
        mode: str = "coordinate",
    ) -> str:
        """Create and run a sub-team for a specific subtask.

        Args:
            task: The subtask description.
            agent_names: Comma-separated agent names from the pool.
            mode: Team mode:
                  - "coordinate" — leader delegates sequentially (default)
                  - "route" — single best agent handles the task
                  - "broadcast" — all agents work in parallel, leader synthesizes
                  - "tasks" — autonomous task loop: leader decomposes into tasks,
                    delegates, tracks progress, iterates until done

        Returns:
            The team's response.
        """
        if self.current_depth >= self.max_depth:
            return (
                f"Error: Maximum nesting depth ({self.max_depth}) reached. "
                f"Complete this task without spawning sub-teams."
            )

        names = [n.strip() for n in agent_names.split(",") if n.strip()]

        if limit_err := self._check_agent_limit(len(names)):
            return limit_err
        if not names:
            return "Error: No agent names provided."

        # If only one agent, just spawn it directly
        if len(names) == 1:
            return self.spawn_agent(task, names[0])

        try:
            from agno.team.team import Team

            members = []
            for name in names:
                try:
                    members.append(self.pool.get(name))
                except KeyError as e:
                    return str(e)

            valid_modes = ("route", "coordinate", "broadcast", "tasks")
            if mode not in valid_modes:
                mode = "coordinate"

            team_kwargs = {
                "name": f"sub-team-depth-{self.current_depth + 1}",
                "mode": mode,
                "members": members,
                "markdown": True,
            }
            if mode == "tasks":
                team_kwargs["max_iterations"] = self.settings.orchestration.max_task_iterations

            team = Team(**team_kwargs)

            self._fire_hook(
                "SubagentStart",
                {
                    "agent_name": f"team({','.join(names)})",
                    "task": task[:500],
                    "mode": mode,
                },
            )

            import asyncio

            async def _run():
                response = await team.arun(task)
                if hasattr(response, "content"):
                    return str(response.content)
                return str(response)

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures

                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(asyncio.run, _run())
                        result = future.result(timeout=self.settings.orchestration.sub_team_timeout)
                else:
                    result = loop.run_until_complete(_run())
            except RuntimeError:
                result = asyncio.run(_run())

            self._fire_hook(
                "SubagentStop",
                {
                    "agent_name": f"team({','.join(names)})",
                    "result_preview": result[:500],
                },
            )
            return result
        except TimeoutError:
            error = (
                f"Error: Sub-team timed out after {self.settings.orchestration.sub_team_timeout}s."
            )
            self._fire_hook(
                "SubagentStop", {"agent_name": f"team({','.join(names)})", "error": error}
            )
            return error
        except Exception as e:
            error = f"Error running sub-team: {e}"
            self._fire_hook(
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

        Use this when the current team lacks a specialist for the task.
        The agent is temporary and stored in .ember/agents.tmp/.

        Args:
            name: Short snake_case name for the agent.
            description: One-line description of what the agent does.
            system_prompt: Full system prompt defining the agent's behavior.
            tools: Comma-separated tool names (default: Read,Write,Edit,Bash,Grep,Glob).

        Returns:
            Confirmation message with the agent name.
        """
        tool_list = [t.strip() for t in tools.split(",") if t.strip()]
        try:
            self.pool.register_ephemeral(
                name=name,
                description=description,
                system_prompt=system_prompt,
                tools=tool_list,
            )
            return (
                f"Created ephemeral agent '{name}': {description}. "
                f"You can now use spawn_agent(task, '{name}') to delegate work to it."
            )
        except (ValueError, RuntimeError) as e:
            return f"Error creating agent: {e}"


def reset_agent_counter(session_id: str) -> None:
    """Reset the spawned-agent counter for a session. Call on session end."""
    with _agent_counter_lock:
        _agent_counters.pop(session_id, None)
