"""OrchestrateTools — allows agents to spawn sub-teams at runtime."""

from typing import TYPE_CHECKING

from agno.tools import Toolkit

if TYPE_CHECKING:
    from ember_code.config.settings import Settings
    from ember_code.pool import AgentPool


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
    ):
        super().__init__(name="ember_orchestrate")
        self.pool = pool
        self.settings = settings
        self.current_depth = current_depth
        self.max_depth = settings.orchestration.max_nesting_depth
        self.register(self.spawn_agent)
        self.register(self.spawn_team)

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

        try:
            agent = self.pool.get(agent_name)
        except KeyError as e:
            return str(e)

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
                        return future.result(timeout=self.settings.orchestration.sub_team_timeout)
                return loop.run_until_complete(_run())
            except RuntimeError:
                return asyncio.run(_run())
        except TimeoutError:
            return f"Error: Sub-agent '{agent_name}' timed out after {self.settings.orchestration.sub_team_timeout}s."
        except Exception as e:
            return f"Error running sub-agent '{agent_name}': {e}"

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
            mode: Team mode — "route" or "coordinate".

        Returns:
            The team's response.
        """
        if self.current_depth >= self.max_depth:
            return (
                f"Error: Maximum nesting depth ({self.max_depth}) reached. "
                f"Complete this task without spawning sub-teams."
            )

        names = [n.strip() for n in agent_names.split(",") if n.strip()]
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

            if mode not in ("route", "coordinate"):
                mode = "coordinate"

            team = Team(
                name=f"sub-team-depth-{self.current_depth + 1}",
                mode=mode,
                members=members,
                markdown=True,
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
                        return future.result(timeout=self.settings.orchestration.sub_team_timeout)
                return loop.run_until_complete(_run())
            except RuntimeError:
                return asyncio.run(_run())
        except TimeoutError:
            return (
                f"Error: Sub-team timed out after {self.settings.orchestration.sub_team_timeout}s."
            )
        except Exception as e:
            return f"Error running sub-team: {e}"
