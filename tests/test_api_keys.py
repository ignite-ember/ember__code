"""Tests for config/api_keys.py — API key resolution."""

from ember_code.config.api_keys import resolve_api_key


class TestResolveApiKey:
    def test_direct_key(self):
        entry = {"api_key": "sk-abc123"}
        assert resolve_api_key(entry) == "sk-abc123"

    def test_env_var(self, monkeypatch):
        monkeypatch.setenv("TEST_API_KEY", "sk-from-env")
        entry = {"api_key_env": "TEST_API_KEY"}
        assert resolve_api_key(entry) == "sk-from-env"

    def test_env_var_missing(self, monkeypatch):
        monkeypatch.delenv("NONEXISTENT_KEY", raising=False)
        entry = {"api_key_env": "NONEXISTENT_KEY"}
        assert resolve_api_key(entry) is None

    def test_cmd(self):
        entry = {"api_key_cmd": "echo sk-from-cmd"}
        result = resolve_api_key(entry)
        assert result == "sk-from-cmd"

    def test_cmd_strips_whitespace(self):
        entry = {"api_key_cmd": "echo '  sk-trimmed  '"}
        result = resolve_api_key(entry)
        assert result == "sk-trimmed"

    def test_priority_direct_over_env(self, monkeypatch):
        monkeypatch.setenv("TEST_KEY", "from-env")
        entry = {"api_key": "from-direct", "api_key_env": "TEST_KEY"}
        assert resolve_api_key(entry) == "from-direct"

    def test_priority_env_over_cmd(self, monkeypatch):
        monkeypatch.setenv("TEST_KEY", "from-env")
        entry = {"api_key_env": "TEST_KEY", "api_key_cmd": "echo from-cmd"}
        assert resolve_api_key(entry) == "from-env"

    def test_empty_entry(self):
        assert resolve_api_key({}) is None

    def test_cmd_failure_returns_none(self):
        entry = {"api_key_cmd": "false"}  # command that exits non-zero
        assert resolve_api_key(entry) is None
