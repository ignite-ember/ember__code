"""MCP configuration — loads MCP server definitions."""

import json
from pathlib import Path

from pydantic import BaseModel, Field


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server."""

    name: str
    type: str = "stdio"
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str = ""


class MCPConfigLoader:
    """Loads MCP server configurations from .mcp.json files."""

    def __init__(self, project_dir: Path | None = None):
        self.project_dir = project_dir or Path.cwd()

    def load(self) -> dict[str, MCPServerConfig]:
        """Load MCP server configurations from all locations."""
        servers: dict[str, MCPServerConfig] = {}

        paths = [
            Path.home() / ".ember" / ".mcp.json",
            self.project_dir / ".mcp.json",
        ]

        for path in paths:
            self._load_from_file(path, servers)

        return servers

    def _load_from_file(self, path: Path, servers: dict[str, MCPServerConfig]) -> None:
        """Load config from a single .mcp.json file."""
        if not path.exists():
            return

        try:
            with open(path) as f:
                data = json.load(f)

            mcp_servers = data.get("mcpServers", {})
            for name, config in mcp_servers.items():
                servers[name] = MCPServerConfig(
                    name=name,
                    type=config.get("type", "stdio"),
                    command=config.get("command", ""),
                    args=config.get("args", []),
                    env=config.get("env", {}),
                    url=config.get("url", ""),
                )
        except (json.JSONDecodeError, OSError):
            pass


# Backward compatibility
def load_mcp_config(project_dir: Path | None = None) -> dict[str, MCPServerConfig]:
    """Convenience wrapper around MCPConfigLoader.load()."""
    return MCPConfigLoader(project_dir).load()
