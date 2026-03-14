"""MCP server — exposes Ember Code tools to IDEs via stdio."""

from typing import Any


class MCPServerFactory:
    """Creates and configures MCP servers for IDE integration."""

    def __init__(self, settings: Any = None):
        self.settings = settings

    def create(self) -> Any:
        """Create an MCP server that exposes Ember Code tools.

        Returns:
            An MCP server instance, or None if MCP is not available.
        """
        try:
            from mcp.server import Server
        except ImportError:
            return None

        server = Server("ember-code")
        self._register_tools(server)
        return server

    def _register_tools(self, server: Any) -> None:
        """Register tool handlers on the server."""

        @server.list_tools()
        async def list_tools():
            from mcp.types import Tool

            return [
                Tool(
                    name="ember_chat",
                    description="Send a message to Ember Code and get a response",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "message": {
                                "type": "string",
                                "description": "The message to send",
                            },
                        },
                        "required": ["message"],
                    },
                ),
                Tool(
                    name="ember_edit",
                    description="Edit a file using targeted string replacement",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string", "description": "Path to the file"},
                            "old_string": {"type": "string", "description": "Text to find"},
                            "new_string": {"type": "string", "description": "Replacement text"},
                        },
                        "required": ["file_path", "old_string", "new_string"],
                    },
                ),
            ]

        @server.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]):
            from mcp.types import TextContent

            if name == "ember_chat":
                message = arguments.get("message", "")
                return [TextContent(type="text", text=f"Ember Code received: {message}")]

            elif name == "ember_edit":
                from ember_code.tools.edit import EmberEditTools

                tools = EmberEditTools()
                result = tools.edit_file(
                    arguments["file_path"],
                    arguments["old_string"],
                    arguments["new_string"],
                )
                return [TextContent(type="text", text=result)]

            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    async def run_stdio(self) -> None:
        """Run the MCP server over stdio."""
        try:
            from mcp.server.stdio import stdio_server
        except ImportError:
            print("MCP support requires the 'mcp' package. Install: pip install ember-code[mcp]")
            return

        server = self.create()
        if server is None:
            return

        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream)


# Backward compatibility
def create_mcp_server(settings: Any = None) -> Any:
    """Convenience wrapper around MCPServerFactory.create()."""
    return MCPServerFactory(settings).create()


async def run_mcp_server(settings: Any = None):
    """Convenience wrapper around MCPServerFactory.run_stdio()."""
    await MCPServerFactory(settings).run_stdio()
