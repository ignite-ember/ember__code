"""MCP integration — Model Context Protocol server and client."""

from ember_code.mcp.client import MCPClientManager
from ember_code.mcp.config import MCPConfigLoader, MCPServerConfig, load_mcp_config
from ember_code.mcp.server import MCPServerFactory, create_mcp_server
from ember_code.mcp.tools import MCPToolProvider, get_mcp_tools_for_agent

__all__ = [
    "MCPServerFactory",
    "create_mcp_server",
    "MCPClientManager",
    "MCPConfigLoader",
    "MCPServerConfig",
    "load_mcp_config",
    "MCPToolProvider",
    "get_mcp_tools_for_agent",
]
