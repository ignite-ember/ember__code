"""MCP client — connects to external MCP servers."""

import contextlib
import logging
import os
from typing import Any

from ember_code.mcp.approval import MCPApprovalManager
from ember_code.mcp.config import MCPConfigLoader, MCPPolicy

logger = logging.getLogger(__name__)


@contextlib.contextmanager
def _suppress_subprocess_output():
    """Suppress stderr to prevent MCP subprocess messages from corrupting the TUI.

    MCP servers (e.g. vscode-mcp-server) print startup banners to stderr,
    which bleeds into the Textual terminal display. Redirects stderr to
    /dev/null during connection. Stdout is left alone since Textual uses it.
    """
    devnull = os.open(os.devnull, os.O_WRONLY)
    old_stderr = os.dup(2)
    try:
        os.dup2(devnull, 2)
        yield
    finally:
        os.dup2(old_stderr, 2)
        os.close(old_stderr)
        os.close(devnull)


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
            elif config.type == "stdio":
                command = " ".join([config.command, *config.args])
                mcp_tools = MCPTools(
                    command=command,
                    env=config.env if config.env else None,
                    transport="stdio",
                )
            else:
                self._errors[name] = f"Unsupported MCP type: {config.type}"
                return None

            with _suppress_subprocess_output():
                await mcp_tools.__aenter__()

            # Verify the MCP server actually provides tools — an empty
            # toolset means the IDE plugin isn't active or the endpoint
            # is unreachable (e.g. JetBrains MCP proxy found no IDE).
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
