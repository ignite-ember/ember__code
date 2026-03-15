"""Agent Pool — loads, parses, and manages agent definitions from .md files."""

import re
import sys
from pathlib import Path
from typing import Any

import yaml
from agno.agent import Agent
from pydantic import BaseModel, Field

from ember_code.config.models import ModelRegistry
from ember_code.config.settings import Settings
from ember_code.tools.registry import resolve_tools


class AgentDefinition(BaseModel):
    """Parsed agent definition from a .md file."""

    name: str
    description: str
    tools: list[str] = Field(default_factory=list)
    model: str | None = None
    color: str | None = None
    reasoning: bool = False
    reasoning_min_steps: int = 1
    reasoning_max_steps: int = 10
    tags: list[str] = Field(default_factory=list)
    can_orchestrate: bool = True
    mcp_servers: list[str] = Field(default_factory=list)
    max_turns: int | None = None
    temperature: float | None = None
    system_prompt: str = ""
    source_path: Path | None = None


class AgentEntry(BaseModel):
    """An agent in the pool with its definition, priority, and built agent."""

    model_config = {"arbitrary_types_allowed": True}

    definition: AgentDefinition
    priority: int  # 0=built-in, 1=global, 2=project-local, 3=project
    agent: Any = None  # Agno Agent — typed as Any to avoid forward-ref issues


class AgentParser:
    """Parses agent .md files and builds Agno Agent instances."""

    @staticmethod
    def parse(path: Path) -> AgentDefinition:
        """Parse a .md file with YAML frontmatter into an AgentDefinition."""
        content = path.read_text()

        frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)", content, re.DOTALL)
        if not frontmatter_match:
            raise ValueError(f"No YAML frontmatter found in {path}")

        yaml_str = frontmatter_match.group(1)
        body = frontmatter_match.group(2).strip()
        fm = yaml.safe_load(yaml_str) or {}

        if "name" not in fm:
            raise ValueError(f"Agent definition missing 'name' in {path}")
        if "description" not in fm:
            raise ValueError(f"Agent definition missing 'description' in {path}")

        # Parse tools
        tools_raw = fm.get("tools", [])
        if isinstance(tools_raw, str):
            tools = [t.strip() for t in tools_raw.split(",") if t.strip()]
        elif isinstance(tools_raw, list):
            tools = tools_raw
        else:
            tools = []

        # Parse tags
        tags = fm.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]

        return AgentDefinition(
            name=fm["name"],
            description=fm["description"],
            tools=tools,
            model=fm.get("model"),
            color=fm.get("color"),
            reasoning=fm.get("reasoning", False),
            reasoning_min_steps=fm.get("reasoning_min_steps", 1),
            reasoning_max_steps=fm.get("reasoning_max_steps", 10),
            tags=tags,
            can_orchestrate=fm.get("can_orchestrate", True),
            mcp_servers=fm.get("mcp_servers", []),
            max_turns=fm.get("max_turns"),
            temperature=fm.get("temperature"),
            system_prompt=body,
            source_path=path,
        )

    @staticmethod
    def build_agent(
        definition: AgentDefinition,
        settings: Settings,
        base_dir: str | None = None,
    ) -> Agent:
        """Build an Agno Agent from an AgentDefinition."""
        # If the agent hardcodes the built-in default model, honour the
        # user's configured default instead (so BYOM overrides propagate).
        BUILTIN_DEFAULT = "MiniMax-M2.5"
        agent_model = definition.model
        if not agent_model or agent_model == BUILTIN_DEFAULT:
            agent_model = settings.models.default
        model = ModelRegistry(settings).get_model(agent_model)

        tools = []
        if definition.tools:
            tools = resolve_tools(definition.tools, base_dir=base_dir)

        kwargs: dict[str, Any] = {
            "name": definition.name,
            "model": model,
            "description": definition.description,
            "instructions": [definition.system_prompt] if definition.system_prompt else None,
            "tools": tools if tools else None,
            "markdown": True,
        }

        if definition.reasoning:
            kwargs["reasoning"] = True
            kwargs["reasoning_min_steps"] = definition.reasoning_min_steps
            kwargs["reasoning_max_steps"] = definition.reasoning_max_steps

        if definition.temperature is not None:
            model.temperature = definition.temperature

        return Agent(**kwargs)


class AgentPool:
    """Manages the pool of available agents.

    Loads agents from multiple directories with priority-based conflict resolution:
    - Priority 0: Built-in agents (lowest)
    - Priority 1: Global user agents (~/.ember/agents/)
    - Priority 2: Project local agents (.ember/agents.local/)
    - Priority 3: Project agents (.ember/agents/) (highest)
    """

    def __init__(self):
        self.entries: dict[str, AgentEntry] = {}
        self._parser = AgentParser()

    def load_directory(
        self, path: Path, priority: int, settings: Settings, base_dir: str | None = None
    ):
        """Load all .md agent files from a directory."""
        if not path.exists():
            return

        for md_file in sorted(path.glob("*.md")):
            try:
                definition = self._parser.parse(md_file)
                name = definition.name

                if name not in self.entries or priority > self.entries[name].priority:
                    agent = self._parser.build_agent(definition, settings, base_dir)
                    self.entries[name] = AgentEntry(
                        definition=definition,
                        priority=priority,
                        agent=agent,
                    )
            except Exception as e:
                print(f"Warning: Failed to load agent from {md_file}: {e}", file=sys.stderr)

    def load_all(self, settings: Settings, project_dir: Path | None = None):
        """Load agents from all directories in priority order."""
        if project_dir is None:
            project_dir = Path.cwd()

        base_dir = str(project_dir)

        # Priority 0: Built-in agents
        builtin_dir = Path(__file__).parent.parent.parent / "agents"
        self.load_directory(builtin_dir, priority=0, settings=settings, base_dir=base_dir)

        # Priority 1: Global user agents
        global_dir = Path.home() / ".ember" / "agents"
        self.load_directory(global_dir, priority=1, settings=settings, base_dir=base_dir)

        # Priority 2: Project local agents (gitignored)
        local_dir = project_dir / ".ember" / "agents.local"
        self.load_directory(local_dir, priority=2, settings=settings, base_dir=base_dir)

        # Priority 3: Project agents
        project_agents_dir = project_dir / ".ember" / "agents"
        self.load_directory(project_agents_dir, priority=3, settings=settings, base_dir=base_dir)

        # Cross-tool support: Claude Code directories
        if settings.agents.cross_tool_support:
            claude_project = project_dir / ".claude" / "agents"
            self.load_directory(claude_project, priority=2, settings=settings, base_dir=base_dir)
            claude_global = Path.home() / ".claude" / "agents"
            self.load_directory(claude_global, priority=1, settings=settings, base_dir=base_dir)

    def get(self, name: str) -> Agent:
        """Get an agent by name."""
        if name not in self.entries:
            available = ", ".join(sorted(self.entries.keys()))
            raise KeyError(f"Agent not found: '{name}'. Available: {available}")
        return self.entries[name].agent

    def get_definition(self, name: str) -> AgentDefinition:
        """Get an agent definition by name."""
        if name not in self.entries:
            raise KeyError(f"Agent not found: '{name}'")
        return self.entries[name].definition

    def list_agents(self) -> list[AgentDefinition]:
        """List all agent definitions."""
        return [entry.definition for entry in self.entries.values()]

    def describe(self) -> str:
        """Generate a summary of all agents for the Orchestrator."""
        lines = []
        for entry in self.entries.values():
            d = entry.definition
            tools_str = ", ".join(d.tools) if d.tools else "none"
            tags_str = ", ".join(d.tags) if d.tags else "none"
            lines.append(f"- **{d.name}**: {d.description} [tools: {tools_str}] [tags: {tags_str}]")
        return "\n".join(lines)

    @property
    def agent_names(self) -> list[str]:
        """Get sorted list of agent names."""
        return sorted(self.entries.keys())
