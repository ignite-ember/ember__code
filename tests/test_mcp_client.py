"""Tests for mcp/client.py — MCP client connection management."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ember_code.mcp.client import MCPClientManager


class TestMCPClientManager:
    def _make_manager(self, configs=None):
        with (
            patch("ember_code.mcp.client.MCPConfigLoader") as MockLoader,
            patch("ember_code.mcp.client.MCPApprovalManager") as MockApproval,
            patch("ember_code.mcp.config.MCPPolicy.from_managed_settings") as mock_from,
        ):
            MockLoader.return_value.load.return_value = configs or {}
            # Auto-approve everything in existing tests
            MockApproval.return_value.check_approval.return_value = True
            from ember_code.mcp.config import MCPPolicy

            mock_from.return_value = MCPPolicy()
            return MCPClientManager(project_dir="/tmp/test")

    def test_list_servers_empty(self):
        mgr = self._make_manager()
        assert mgr.list_servers() == []

    def test_list_servers_returns_names(self):
        configs = {"server1": MagicMock(), "server2": MagicMock()}
        mgr = self._make_manager(configs)
        assert set(mgr.list_servers()) == {"server1", "server2"}

    def test_list_connected_initially_empty(self):
        mgr = self._make_manager({"s1": MagicMock()})
        assert mgr.list_connected() == []

    def test_get_error_empty_initially(self):
        mgr = self._make_manager()
        assert mgr.get_error("unknown") == ""

    @pytest.mark.asyncio
    async def test_connect_missing_config(self):
        mgr = self._make_manager()
        result = await mgr.connect("nonexistent")
        assert result is None
        assert "No config" in mgr.get_error("nonexistent")

    @pytest.mark.asyncio
    async def test_connect_unsupported_type(self):
        config = MagicMock()
        config.type = "grpc"
        mgr = self._make_manager({"test": config})
        result = await mgr.connect("test")
        assert result is None
        assert "Unsupported" in mgr.get_error("test")

    @pytest.mark.asyncio
    async def test_connect_sse_missing_url(self):
        config = MagicMock()
        config.type = "sse"
        config.url = ""
        mgr = self._make_manager({"sse-server": config})
        result = await mgr.connect("sse-server")
        assert result is None
        assert "url" in mgr.get_error("sse-server").lower()

    @pytest.mark.asyncio
    async def test_connect_stdio_success(self):
        config = MagicMock()
        config.type = "stdio"
        config.command = "node"
        config.args = ["server.js"]
        config.env = {}

        mock_mcp_tools = MagicMock()
        mock_mcp_tools.__aenter__ = AsyncMock(return_value=mock_mcp_tools)
        mock_mcp_tools.__aexit__ = AsyncMock()
        mock_mcp_tools.functions = {"tool1": MagicMock()}

        mgr = self._make_manager({"my-server": config})
        with patch("agno.tools.mcp.MCPTools", return_value=mock_mcp_tools):
            result = await mgr.connect("my-server")
            assert result is mock_mcp_tools
            assert "my-server" in mgr.list_connected()

    @pytest.mark.asyncio
    async def test_connect_returns_cached(self):
        config = MagicMock()
        config.type = "stdio"
        config.command = "node"
        config.args = []
        config.env = {}

        mock_mcp_tools = MagicMock()
        mock_mcp_tools.__aenter__ = AsyncMock(return_value=mock_mcp_tools)
        mock_mcp_tools.__aexit__ = AsyncMock()
        mock_mcp_tools.functions = {"tool1": MagicMock()}

        mgr = self._make_manager({"cached": config})
        with patch("agno.tools.mcp.MCPTools", return_value=mock_mcp_tools):
            first = await mgr.connect("cached")
            second = await mgr.connect("cached")
            assert first is second

    @pytest.mark.asyncio
    async def test_connect_no_tools_closes(self):
        config = MagicMock()
        config.type = "stdio"
        config.command = "node"
        config.args = []
        config.env = {}

        mock_mcp_tools = MagicMock()
        mock_mcp_tools.__aenter__ = AsyncMock(return_value=mock_mcp_tools)
        mock_mcp_tools.__aexit__ = AsyncMock()
        mock_mcp_tools.functions = {}  # no tools

        mgr = self._make_manager({"empty": config})
        with patch("agno.tools.mcp.MCPTools", return_value=mock_mcp_tools):
            result = await mgr.connect("empty")
            assert result is None
            assert "no tools" in mgr.get_error("empty").lower()
            mock_mcp_tools.__aexit__.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_import_error(self):
        config = MagicMock()
        config.type = "stdio"
        config.command = "node"
        config.args = []
        config.env = {}

        mgr = self._make_manager({"broken": config})
        with patch("agno.tools.mcp.MCPTools", side_effect=ImportError("no mcp")):
            result = await mgr.connect("broken")
            assert result is None
            assert "not installed" in mgr.get_error("broken").lower()

    @pytest.mark.asyncio
    async def test_disconnect_all(self):
        mgr = self._make_manager()
        mock_client = MagicMock()
        mock_client.__aexit__ = AsyncMock()
        mgr._clients = {"s1": mock_client}
        mgr.configs = {"s1": MagicMock(type="stdio")}

        await mgr.disconnect_all()
        assert mgr._clients == {}
        mock_client.__aexit__.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_skips_sse(self):
        mgr = self._make_manager()
        mock_client = MagicMock()
        mock_client.__aexit__ = AsyncMock()
        mgr._clients = {"sse": mock_client}
        mgr.configs = {"sse": MagicMock(type="sse")}

        await mgr.disconnect_all()
        assert mgr._clients == {}
        mock_client.__aexit__.assert_not_called()
