"""MCP client — connects to external MCP servers."""

import contextlib
from typing import Any

from ember_code.mcp.config import load_mcp_config


class MCPClientManager:
    """Manages connections to external MCP servers."""

    def __init__(self, project_dir=None):
        self.configs = load_mcp_config(project_dir)
        self._clients: dict[str, Any] = {}

    async def connect(self, name: str) -> Any | None:
        """Connect to an MCP server by name.

        Returns Agno MCPTools instance or None if connection fails.
        """
        if name in self._clients:
            return self._clients[name]

        config = self.configs.get(name)
        if not config:
            return None

        try:
            from agno.tools.mcp import MCPTools

            if config.type == "stdio":
                from agno.tools.mcp import StdioServerParameters

                server_params = StdioServerParameters(
                    command=config.command,
                    args=config.args,
                    env=config.env if config.env else None,
                )
                mcp_tools = MCPTools(server_params=server_params)
            else:
                return None

            await mcp_tools.__aenter__()
            self._clients[name] = mcp_tools
            return mcp_tools
        except ImportError:
            return None
        except Exception:
            return None

    async def disconnect_all(self):
        """Disconnect from all MCP servers."""
        for _name, client in self._clients.items():
            with contextlib.suppress(Exception):
                await client.__aexit__(None, None, None)
        self._clients.clear()

    def list_servers(self) -> list[str]:
        """List available MCP server names."""
        return list(self.configs.keys())

    def list_connected(self) -> list[str]:
        """List currently connected MCP server names."""
        return list(self._clients.keys())
