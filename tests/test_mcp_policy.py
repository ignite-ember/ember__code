"""Tests for MCP managed policy — MCPPolicy model and from_managed_settings()."""

import json
from pathlib import Path
from unittest.mock import patch

from ember_code.mcp.config import MCPPolicy


class TestMCPPolicy:
    """Unit tests for the MCPPolicy model."""

    def test_defaults(self):
        policy = MCPPolicy()
        assert policy.required == []
        assert policy.allowed == []
        assert policy.denied == []

    def test_is_denied_exact(self):
        policy = MCPPolicy(denied=["evil-server"])
        assert policy.is_denied("evil-server") is True
        assert policy.is_denied("good-server") is False

    def test_is_denied_glob(self):
        policy = MCPPolicy(denied=["test-*", "*.local"])
        assert policy.is_denied("test-foo") is True
        assert policy.is_denied("test-bar") is True
        assert policy.is_denied("my.local") is True
        assert policy.is_denied("production") is False

    def test_is_allowed_empty_allows_all(self):
        policy = MCPPolicy()
        assert policy.is_allowed("anything") is True

    def test_is_allowed_explicit_list(self):
        policy = MCPPolicy(allowed=["server-a", "server-b"])
        assert policy.is_allowed("server-a") is True
        assert policy.is_allowed("server-b") is True
        assert policy.is_allowed("server-c") is False

    def test_denied_overrides_allowed(self):
        policy = MCPPolicy(allowed=["server-a"], denied=["server-a"])
        assert policy.is_allowed("server-a") is False

    def test_denied_glob_overrides_allowed(self):
        policy = MCPPolicy(allowed=["test-server"], denied=["test-*"])
        assert policy.is_allowed("test-server") is False

    def test_required_field(self):
        policy = MCPPolicy(required=["mandatory-server"])
        assert "mandatory-server" in policy.required


class TestFromManagedSettings:
    """Tests for MCPPolicy.from_managed_settings() classmethod."""

    def test_returns_empty_policy_when_no_file(self):
        with (
            patch("ember_code.mcp.config.platform.system", return_value="Darwin"),
            patch("ember_code.mcp.config.Path.exists", return_value=False),
        ):
            policy = MCPPolicy.from_managed_settings()
        assert policy == MCPPolicy()

    def test_returns_empty_policy_on_unsupported_platform(self):
        with patch("ember_code.mcp.config.platform.system", return_value="Windows"):
            policy = MCPPolicy.from_managed_settings()
        assert policy == MCPPolicy()

    def test_loads_policy_from_file(self, tmp_path):
        settings_file = tmp_path / "managed-settings.json"
        settings_file.write_text(
            json.dumps(
                {
                    "mcp": {
                        "required": ["company-server"],
                        "allowed": ["company-server", "vscode"],
                        "denied": ["untrusted-*"],
                    }
                }
            )
        )

        def fake_path(path_str):
            if "EmberCode" in str(path_str):
                return settings_file
            return Path(path_str)

        with (
            patch("ember_code.mcp.config.platform.system", return_value="Darwin"),
            patch("ember_code.mcp.config.Path", side_effect=fake_path),
        ):
            policy = MCPPolicy.from_managed_settings()

        assert policy.required == ["company-server"]
        assert policy.is_allowed("vscode") is True
        assert policy.is_denied("untrusted-foo") is True

    def test_handles_corrupt_json(self, tmp_path):
        """Verify from_managed_settings handles corrupt JSON gracefully."""
        settings_file = tmp_path / "managed-settings.json"
        settings_file.write_text("not valid json{{{")

        def fake_path(path_str):
            if "EmberCode" in str(path_str):
                return settings_file
            return Path(path_str)

        with (
            patch("ember_code.mcp.config.platform.system", return_value="Darwin"),
            patch("ember_code.mcp.config.Path", side_effect=fake_path),
        ):
            policy = MCPPolicy.from_managed_settings()

        assert policy == MCPPolicy()

    def test_handles_missing_mcp_key(self, tmp_path):
        settings_file = tmp_path / "managed-settings.json"
        settings_file.write_text(json.dumps({"other_setting": True}))

        def fake_path(path_str):
            if "EmberCode" in str(path_str):
                return settings_file
            return Path(path_str)

        with (
            patch("ember_code.mcp.config.platform.system", return_value="Darwin"),
            patch("ember_code.mcp.config.Path", side_effect=fake_path),
        ):
            policy = MCPPolicy.from_managed_settings()

        assert policy == MCPPolicy()


class TestFromManagedSettingsIntegration:
    """Integration-style tests that exercise from_managed_settings with real temp files."""

    def test_darwin_path(self, tmp_path):
        """Test that macOS path is used correctly."""
        managed = tmp_path / "managed-settings.json"
        managed.write_text(json.dumps({"mcp": {"denied": ["bad-*"], "required": ["corp"]}}))

        def fake_path_init(path_str):
            if "EmberCode" in str(path_str):
                return managed
            return Path(path_str)

        with (
            patch("ember_code.mcp.config.platform.system", return_value="Darwin"),
            patch("ember_code.mcp.config.Path", side_effect=fake_path_init),
        ):
            policy = MCPPolicy.from_managed_settings()

        assert policy.denied == ["bad-*"]
        assert policy.required == ["corp"]

    def test_linux_path(self, tmp_path):
        """Test that Linux path is used correctly."""
        managed = tmp_path / "managed-settings.json"
        managed.write_text(json.dumps({"mcp": {"allowed": ["approved-only"]}}))

        def fake_path_init(path_str):
            if "ignite-ember" in str(path_str):
                return managed
            return Path(path_str)

        with (
            patch("ember_code.mcp.config.platform.system", return_value="Linux"),
            patch("ember_code.mcp.config.Path", side_effect=fake_path_init),
        ):
            policy = MCPPolicy.from_managed_settings()

        assert policy.allowed == ["approved-only"]
