"""Tests for config/models.py."""

import pytest

from ember_code.core.config.models import (
    DEFAULT_CONTEXT_WINDOW,
    ContextWindowResolver,
    ModelRegistry,
)
from ember_code.core.config.settings import ModelsConfig, Settings, load_settings


@pytest.fixture
def registry():
    return ModelRegistry(load_settings())


class TestModelRegistry:
    def test_default_models_in_config_registry(self, registry):
        # Defaults come from defaults.py -> Settings.models.registry
        assert "MiniMax-M2.7" in registry.settings.models.registry

    def test_resolve_default_entry(self, registry):
        entry = registry._resolve_entry("MiniMax-M2.7")
        assert entry is not None
        assert entry["provider"] == "openai_like"
        assert entry["model_id"] == "MiniMax-Text-01"
        assert entry["context_window"] == 204_800

    def test_resolve_provider_colon_format(self, registry):
        entry = registry._resolve_entry("openai_like:gpt-4o")
        assert entry == {"provider": "openai_like", "model_id": "gpt-4o"}

    def test_resolve_unknown_returns_none(self, registry):
        entry = registry._resolve_entry("nonexistent-model")
        assert entry is None

    def test_resolve_user_registry_overrides(self):
        settings = Settings(
            models=ModelsConfig(
                registry={
                    "MiniMax-M2.7": {
                        "provider": "openai_like",
                        "model_id": "custom-override",
                        "url": "https://example.com/v1",
                    }
                }
            )
        )
        reg = ModelRegistry(settings)
        entry = reg._resolve_entry("MiniMax-M2.7")
        assert entry["model_id"] == "custom-override"

    def test_resolve_custom_model(self):
        settings = Settings(
            models=ModelsConfig(
                registry={
                    "my-model": {
                        "provider": "openai_like",
                        "model_id": "my-custom-id",
                        "url": "https://example.com/v1",
                    }
                }
            )
        )
        reg = ModelRegistry(settings)
        entry = reg._resolve_entry("my-model")
        assert entry["model_id"] == "my-custom-id"

    def test_get_model_unknown_raises(self, registry):
        with pytest.raises(ValueError, match="Unknown model"):
            registry.get_model("totally-fake-model")

    def test_resolve_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("TEST_KEY", "secret123")
        key = ModelRegistry._resolve_api_key({"api_key_env": "TEST_KEY"})
        assert key == "secret123"

    def test_resolve_api_key_missing_env(self):
        key = ModelRegistry._resolve_api_key({"api_key_env": "NONEXISTENT_KEY_12345"})
        assert key is None

    def test_resolve_api_key_no_config(self):
        key = ModelRegistry._resolve_api_key({})
        assert key is None

    def test_env_model_override(self, monkeypatch):
        monkeypatch.setenv("EMBER_MODEL", "MiniMax-M2.7")
        reg = ModelRegistry(load_settings())
        entry = reg._resolve_entry("MiniMax-M2.7")
        assert entry["model_id"] == "MiniMax-Text-01"

    def test_register_provider(self, registry):
        class FakeProvider:
            pass

        registry.register_provider("fake", FakeProvider)
        assert "fake" in registry.PROVIDERS

    def test_generate_pattern_command(self):
        from ember_code.core.config.permissions import PermissionGuard

        assert PermissionGuard._generate_pattern("npm test") == "npm *"
        assert PermissionGuard._generate_pattern("pytest tests/") == "pytest *"

    def test_get_context_window_from_registry(self, registry):
        ctx = registry.get_context_window("MiniMax-M2.7")
        assert ctx == 204_800

    def test_get_context_window_unknown_fallback(self, registry):
        ctx = registry.get_context_window("openai_like:unknown-model-xyz")
        assert ctx == DEFAULT_CONTEXT_WINDOW


class TestContextWindowResolver:
    def test_explicit_config(self):
        r = ContextWindowResolver()
        result = r.resolve("anything", {"context_window": 32_000})
        assert result == 32_000

    def test_unknown_model_fallback(self):
        r = ContextWindowResolver()
        assert r.resolve("totally-unknown-model") == DEFAULT_CONTEXT_WINDOW

    def test_cache(self):
        r = ContextWindowResolver()
        r._cache["cached-model"] = 50_000
        assert r.resolve("cached-model") == 50_000

    @pytest.mark.asyncio
    async def test_aresolve_explicit(self):
        r = ContextWindowResolver()
        result = await r.aresolve("x", {"context_window": 16_000})
        assert result == 16_000

    @pytest.mark.asyncio
    async def test_aresolve_fallback(self):
        r = ContextWindowResolver()
        result = await r.aresolve("unknown-model-xyz")
        assert result == DEFAULT_CONTEXT_WINDOW
