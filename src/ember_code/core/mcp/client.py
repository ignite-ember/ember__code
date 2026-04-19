"""MCP client — connects to external MCP servers.

For stdio transport, we bypass Agno's default ``MCPTools.__aenter__``
and connect manually using the MCP SDK's ``stdio_client`` with
``errlog`` redirected to a file.  This avoids Textual rendering
corruption caused by subprocess stderr mixing with Textual's output.
"""

import logging
import os
import tempfile
from datetime import timedelta
from typing import Any

from ember_code.core.mcp.approval import MCPApprovalManager
from ember_code.core.mcp.config import MCPConfigLoader, MCPPolicy

logger = logging.getLogger(__name__)

_MCP_ERRLOG_PATH = os.path.join(tempfile.gettempdir(), "ember_mcp_stderr.log")


class MCPClientManager:
    """Manages connections to external MCP servers."""

    def __init__(self, project_dir=None, *, policy: MCPPolicy | None = None):
        self.configs = MCPConfigLoader(project_dir).load()
        self._clients: dict[str, Any] = {}
        self._errors: dict[str, str] = {}
        self._approval = MCPApprovalManager()
        self._policy: MCPPolicy = (
            policy if policy is not None else MCPPolicy.from_managed_settings()
        )

    async def connect(self, name: str) -> Any | None:
        """Connect to an MCP server by name.

        Returns Agno MCPTools instance or None if connection fails.
        """
        if name in self._clients:
            return self._clients[name]

        config = self.configs.get(name)
        if not config:
            self._errors[name] = "No config found"
            return None

        # --- MCP policy enforcement ---
        if self._policy.is_denied(name):
            self._errors[name] = f"Server '{name}' is blocked by admin policy"
            logger.warning("MCP '%s' blocked by managed policy (denied)", name)
            return None

        if not self._policy.is_allowed(name):
            self._errors[name] = f"Server '{name}' is not in the allowed list"
            logger.warning("MCP '%s' blocked by managed policy (not allowed)", name)
            return None

        # --- First-use approval ---
        if not self._approval.check_approval(name, config.source_path):
            self._errors[name] = "User denied MCP server connection"
            logger.info("MCP '%s' denied by user approval prompt", name)
            return None

        try:
            from agno.tools.mcp import MCPTools

            if config.type == "sse":
                if not config.url:
                    self._errors[name] = "SSE transport requires a 'url' field"
                    return None
                mcp_tools = MCPTools(url=config.url, transport="sse")
                await mcp_tools.__aenter__()
            elif config.type == "stdio":
                mcp_tools = await self._connect_stdio(name, config)
            else:
                self._errors[name] = f"Unsupported MCP type: {config.type}"
                return None

            # Verify the MCP server actually provides tools
            functions = getattr(mcp_tools, "functions", None) or {}
            if not functions:
                self._errors[name] = (
                    "MCP server connected but returned no tools. "
                    "Ensure the IDE has MCP support enabled."
                )
                logger.warning("MCP '%s' connected but has no tools — closing", name)
                await mcp_tools.__aexit__(None, None, None)
                return None

            self._clients[name] = mcp_tools
            return mcp_tools
        except ImportError:
            self._errors[name] = "MCP dependencies not installed (pip install agno[mcp])"
            logger.warning("MCP connect '%s' failed: missing dependencies", name)
            return None
        except Exception as exc:
            self._errors[name] = str(exc)
            logger.warning("MCP connect '%s' failed: %s", name, exc)
            return None

    async def _connect_stdio(self, name: str, config: Any) -> Any:
        """Connect to an MCP stdio server with errlog redirected.

        Bypasses Agno's ``MCPTools.__aenter__`` and connects manually
        using the MCP SDK's ``stdio_client`` with ``errlog`` sent to a
        log file instead of ``sys.stderr`` (which Textual uses for
        TUI rendering).
        """
        from agno.tools.mcp import MCPTools
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        errlog = open(_MCP_ERRLOG_PATH, "a")  # noqa: SIM115 — must stay open for MCP session lifetime
        params = StdioServerParameters(
            command=config.command,
            args=config.args or [],
            env=config.env if config.env else None,
        )

        mcp_tools = MCPTools(
            server_params=params,
            transport="stdio",
            tool_name_prefix=f"mcp_{name}",
        )

        # Connect using MCP SDK directly with errlog redirected
        mcp_tools._context = stdio_client(params, errlog=errlog)
        session_params = await mcp_tools._context.__aenter__()
        mcp_tools._active_contexts = [mcp_tools._context]
        read, write = session_params[0:2]

        timeout = getattr(mcp_tools, "timeout_seconds", 30) or 30
        mcp_tools._session_context = ClientSession(
            read, write, read_timeout_seconds=timedelta(seconds=timeout)
        )
        mcp_tools.session = await mcp_tools._session_context.__aenter__()
        mcp_tools._active_contexts.append(mcp_tools._session_context)

        # Initialize Agno tool functions from MCP session.
        # tool_name_prefix ensures MCP tools don't collide with built-in tools
        # (e.g. read_file → mcp_filesystem_read_file)
        await mcp_tools.initialize()
        mcp_tools._errlog = errlog

        return mcp_tools

    def get_error(self, name: str) -> str:
        """Return the last connection error for a server, or empty string."""
        return self._errors.get(name, "")

    async def disconnect_all(self):
        """Disconnect from all MCP servers.

        SSE connections use anyio task groups internally. During shutdown
        the exit may run in a different task than the entry, causing
        RuntimeError from anyio's cancel scope.  For SSE clients we
        skip __aexit__ entirely — the connection is abandoned and the
        OS cleans up the socket on process exit.
        """
        for name, client in list(self._clients.items()):
            transport = getattr(self.configs.get(name), "type", "")
            if transport == "sse":
                # SSE async generators can't be closed across tasks.
                # Just drop the reference — the OS reclaims the socket.
                logger.debug("MCP '%s' (SSE) — abandoning connection", name)
                continue
            try:
                await client.__aexit__(None, None, None)
            except BaseException as exc:
                logger.debug("MCP '%s' disconnect error (safe to ignore): %s", name, exc)
        self._clients.clear()

    async def disconnect_one(self, name: str) -> bool:
        """Disconnect a single MCP server by name. Returns True if disconnected."""
        client = self._clients.pop(name, None)
        self._errors.pop(name, None)
        if client is None:
            return False
        # MCP client __aexit__ triggers anyio cancel scope errors when called
        # from a different task than it was created in. Just abandon the
        # connection — the OS cleans up the subprocess/socket on process exit.
        logger.debug("MCP '%s' — dropping connection reference", name)
        return True

    def get_tools(self, name: str) -> list[str]:
        """Return tool names provided by a connected MCP server."""
        client = self._clients.get(name)
        if client is None:
            return []
        functions = getattr(client, "functions", None) or {}
        return list(functions.keys())

    def get_tool_descriptions(self, name: str) -> dict[str, str]:
        """Return {tool_name: description} for a connected MCP server."""
        client = self._clients.get(name)
        if client is None:
            return {}
        functions = getattr(client, "functions", None) or {}
        return {
            fname: func.description or ""
            for fname, func in functions.items()
            if hasattr(func, "description")
        }

    def list_servers(self) -> list[str]:
        """List available MCP server names."""
        return list(self.configs.keys())

    def list_connected(self) -> list[str]:
        """List currently connected MCP server names."""
        return list(self._clients.keys())

    def list_required(self) -> list[str]:
        """List servers required by admin policy that are not yet connected."""
        connected = set(self._clients.keys())
        return [s for s in self._policy.required if s not in connected]
