"""MCP integration — Model Context Protocol client."""

from ember_code.mcp.approval import MCPApprovalManager
from ember_code.mcp.client import MCPClientManager
from ember_code.mcp.config import MCPConfigLoader, MCPPolicy, MCPServerConfig
from ember_code.mcp.tools import MCPToolProvider

__all__ = [
    "MCPApprovalManager",
    "MCPClientManager",
    "MCPConfigLoader",
    "MCPPolicy",
    "MCPServerConfig",
    "MCPToolProvider",
]
