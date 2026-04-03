"""Tests for mcp/config.py — MCP server configuration loading."""

import json

from ember_code.mcp.config import MCPConfigLoader, MCPServerConfig


class TestMCPServerConfig:
    def test_defaults(self):
        cfg = MCPServerConfig(name="test")
        assert cfg.type == "stdio"
        assert cfg.command == ""
        assert cfg.args == []
        assert cfg.env == {}
        assert cfg.url == ""

    def test_stdio_config(self):
        cfg = MCPServerConfig(
            name="node-server",
            type="stdio",
            command="node",
            args=["server.js", "--port", "3000"],
            env={"NODE_ENV": "production"},
        )
        assert cfg.name == "node-server"
        assert cfg.command == "node"
        assert len(cfg.args) == 3

    def test_sse_config(self):
        cfg = MCPServerConfig(
            name="remote",
            type="sse",
            url="http://localhost:3000/sse",
        )
        assert cfg.type == "sse"
        assert cfg.url == "http://localhost:3000/sse"


class TestMCPConfigLoader:
    def test_load_empty_when_no_files(self, tmp_path):
        loader = MCPConfigLoader(project_dir=tmp_path)
        configs = loader.load()
        assert configs == {}

    def test_load_from_project_mcp_json(self, tmp_path):
        mcp_file = tmp_path / ".mcp.json"
        mcp_file.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "test-server": {
                            "type": "stdio",
                            "command": "node",
                            "args": ["server.js"],
                        }
                    }
                }
            )
        )

        loader = MCPConfigLoader(project_dir=tmp_path)
        configs = loader.load()

        assert "test-server" in configs
        cfg = configs["test-server"]
        assert cfg.command == "node"
        assert cfg.args == ["server.js"]
        assert cfg.type == "stdio"

    def test_load_from_ember_subdir(self, tmp_path):
        ember_dir = tmp_path / ".ember"
        ember_dir.mkdir()
        mcp_file = ember_dir / ".mcp.json"
        mcp_file.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "vscode": {
                            "type": "sse",
                            "url": "http://localhost:9222",
                        }
                    }
                }
            )
        )

        loader = MCPConfigLoader(project_dir=tmp_path)
        configs = loader.load()

        assert "vscode" in configs
        assert configs["vscode"].type == "sse"
        assert configs["vscode"].url == "http://localhost:9222"

    def test_later_file_overrides_earlier(self, tmp_path):
        # Project-level .mcp.json
        (tmp_path / ".mcp.json").write_text(
            json.dumps({"mcpServers": {"server": {"command": "old"}}})
        )

        # .ember/.mcp.json (loaded later, should override)
        ember_dir = tmp_path / ".ember"
        ember_dir.mkdir()
        (ember_dir / ".mcp.json").write_text(
            json.dumps({"mcpServers": {"server": {"command": "new"}}})
        )

        loader = MCPConfigLoader(project_dir=tmp_path)
        configs = loader.load()

        assert configs["server"].command == "new"

    def test_ignores_invalid_json(self, tmp_path):
        (tmp_path / ".mcp.json").write_text("not valid json{{{")
        loader = MCPConfigLoader(project_dir=tmp_path)
        configs = loader.load()
        assert configs == {}

    def test_ignores_missing_mcp_servers_key(self, tmp_path):
        (tmp_path / ".mcp.json").write_text(json.dumps({"other": "data"}))
        loader = MCPConfigLoader(project_dir=tmp_path)
        configs = loader.load()
        assert configs == {}

    def test_multiple_servers(self, tmp_path):
        (tmp_path / ".mcp.json").write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "server-a": {"command": "a"},
                        "server-b": {"command": "b", "type": "stdio"},
                    }
                }
            )
        )

        loader = MCPConfigLoader(project_dir=tmp_path)
        configs = loader.load()

        assert len(configs) == 2
        assert configs["server-a"].command == "a"
        assert configs["server-b"].command == "b"
