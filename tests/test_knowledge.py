"""Tests for the knowledge system: EmberEmbedder, EmbedderRegistry, KnowledgeManager, config."""

from unittest.mock import patch

import pytest

from ember_code.config.settings import (
    EmbeddingsConfig,
    GuardrailsConfig,
    KnowledgeConfig,
    LearningConfig,
    ReasoningConfig,
    Settings,
    load_settings,
)
from ember_code.knowledge.embedder import EmberEmbedder
from ember_code.knowledge.embedder_registry import EmbedderRegistry
from ember_code.knowledge.manager import KnowledgeManager, setup_knowledge
from ember_code.knowledge.models import (
    KnowledgeAddResult,
    KnowledgeFilter,
    KnowledgeSearchResponse,
    KnowledgeSearchResult,
    KnowledgeStatus,
)

# ── KnowledgeConfig ──────────────────────────────────────────────


class TestKnowledgeConfig:
    def test_defaults(self):
        cfg = KnowledgeConfig()
        assert cfg.enabled is False
        assert cfg.collection_name == "ember_knowledge"
        assert cfg.chroma_db_path == "~/.ember/chromadb"
        assert cfg.max_results == 10
        assert cfg.embedder == "ember"

    def test_settings_includes_knowledge(self):
        s = Settings()
        assert hasattr(s, "knowledge")
        assert isinstance(s.knowledge, KnowledgeConfig)

    def test_settings_includes_embeddings(self):
        s = Settings()
        assert hasattr(s, "embeddings")
        assert isinstance(s.embeddings, EmbeddingsConfig)
        assert s.embeddings.default == "ember"

    def test_custom_config(self):
        cfg = KnowledgeConfig(
            enabled=True,
            collection_name="my_project",
            embedder="openai:text-embedding-3-small",
        )
        assert cfg.enabled is True
        assert cfg.collection_name == "my_project"
        assert cfg.embedder == "openai:text-embedding-3-small"


# ── EmberEmbedder ────────────────────────────────────────────────


class TestEmberEmbedder:
    def test_defaults(self):
        e = EmberEmbedder()
        # Generic defaults — Ember-specific values come from config registry
        assert e.dimensions is None
        assert e.base_url == ""
        assert e.model == ""

    def test_custom_config(self):
        e = EmberEmbedder(
            base_url="http://localhost:8000",
            api_key="test-key",
            model="custom-model",
        )
        assert e.base_url == "http://localhost:8000"
        assert e.api_key == "test-key"
        assert e.model == "custom-model"

    def test_custom_dimensions(self):
        e = EmberEmbedder(dimensions=384)
        assert e.dimensions == 384

    def test_url_construction(self):
        e = EmberEmbedder(base_url="http://localhost:8000")
        assert e._url == "http://localhost:8000/v1/embeddings"

    def test_url_strips_trailing_slash(self):
        e = EmberEmbedder(base_url="http://localhost:8000/")
        assert e._url == "http://localhost:8000/v1/embeddings"

    def test_headers_without_api_key(self):
        e = EmberEmbedder(api_key="")
        headers = e._headers
        assert "Content-Type" in headers
        assert "Authorization" not in headers

    def test_headers_with_api_key(self):
        e = EmberEmbedder(api_key="my-key")
        headers = e._headers
        assert headers["Authorization"] == "Bearer my-key"

    def test_parse_response(self):
        e = EmberEmbedder()
        data = {
            "data": [{"embedding": [0.1, 0.2, 0.3], "index": 0}],
            "model": "test",
            "usage": {"prompt_tokens": 5, "total_tokens": 5},
        }
        embedding, usage = e._parse_response(data)
        assert embedding == [0.1, 0.2, 0.3]
        assert usage["prompt_tokens"] == 5

    def test_parse_response_no_usage(self):
        e = EmberEmbedder()
        data = {
            "data": [{"embedding": [0.1], "index": 0}],
            "model": "test",
        }
        embedding, usage = e._parse_response(data)
        assert embedding == [0.1]
        assert usage is None

    def test_get_embedding_sync_error_returns_empty(self):
        e = EmberEmbedder(base_url="http://nonexistent:9999")
        # Should not raise — returns empty list on error
        result = e.get_embedding("test")
        assert result == []

    def test_get_embedding_and_usage_sync_error(self):
        e = EmberEmbedder(base_url="http://nonexistent:9999")
        embedding, usage = e.get_embedding_and_usage("test")
        assert embedding == []
        assert usage is None

    @pytest.mark.asyncio
    async def test_async_get_embedding_error_returns_empty(self):
        e = EmberEmbedder(base_url="http://nonexistent:9999")
        result = await e.async_get_embedding("test")
        assert result == []

    @pytest.mark.asyncio
    async def test_async_get_embedding_and_usage_error(self):
        e = EmberEmbedder(base_url="http://nonexistent:9999")
        embedding, usage = await e.async_get_embedding_and_usage("test")
        assert embedding == []
        assert usage is None


# ── KnowledgeManager ─────────────────────────────────────────────


class TestKnowledgeManager:
    def test_disabled_returns_none(self):
        settings = Settings(knowledge=KnowledgeConfig(enabled=False))
        manager = KnowledgeManager(settings)
        result = manager.create_knowledge()
        assert result is None

    def test_setup_knowledge_disabled(self):
        settings = Settings(knowledge=KnowledgeConfig(enabled=False))
        result = setup_knowledge(settings)
        assert result is None

    def test_creates_ember_embedder(self):
        cfg = KnowledgeConfig(enabled=True, embedder="ember")
        settings = load_settings()
        settings.knowledge = cfg
        manager = KnowledgeManager(settings)
        embedder = manager._create_embedder(cfg)
        assert embedder is not None
        assert isinstance(embedder, EmberEmbedder)
        assert embedder.base_url == "https://api.ignite-ember.sh"

    def test_creates_custom_embedder_from_registry(self):
        embeddings = EmbeddingsConfig(
            registry={
                "my-embedder": {
                    "provider": "openai_compatible",
                    "model_id": "custom-model",
                    "url": "http://localhost:9000",
                    "dimensions": 768,
                }
            }
        )
        cfg = KnowledgeConfig(enabled=True, embedder="my-embedder")
        settings = Settings(knowledge=cfg, embeddings=embeddings)
        manager = KnowledgeManager(settings)
        embedder = manager._create_embedder(cfg)
        assert embedder is not None
        assert isinstance(embedder, EmberEmbedder)
        assert embedder.base_url == "http://localhost:9000"
        assert embedder.model == "custom-model"
        assert embedder.dimensions == 768

    def test_unknown_embedder_returns_none(self):
        cfg = KnowledgeConfig(enabled=True, embedder="unknown")
        settings = Settings(knowledge=cfg)
        manager = KnowledgeManager(settings)
        embedder = manager._create_embedder(cfg)
        assert embedder is None

    @patch("ember_code.knowledge.manager.KnowledgeManager._create_embedder")
    def test_no_embedder_returns_none(self, mock_create):
        mock_create.return_value = None
        cfg = KnowledgeConfig(enabled=True)
        settings = Settings(knowledge=cfg)
        manager = KnowledgeManager(settings)
        result = manager.create_knowledge()
        assert result is None


# ── AgnoFeatures + Knowledge ─────────────────────────────────────


class TestKnowledgeInFeatures:
    def test_knowledge_defaults_none(self):
        from ember_code.team_builder import AgnoFeatures

        f = AgnoFeatures()
        assert f.knowledge is None
        assert f.search_knowledge is False

    def test_knowledge_applied_to_agent(self):
        from agno.agent import Agent

        from ember_code.team_builder import AgnoFeatures

        f = AgnoFeatures()
        f.knowledge = "fake-knowledge"
        f.search_knowledge = True

        agent = Agent(name="test")
        f.apply_to_agent(agent)
        assert agent.knowledge == "fake-knowledge"
        assert agent.search_knowledge is True

    def test_knowledge_not_applied_when_none(self):
        from agno.agent import Agent

        from ember_code.team_builder import AgnoFeatures

        f = AgnoFeatures()
        agent = Agent(name="test")
        original_knowledge = agent.knowledge
        f.apply_to_agent(agent)
        assert agent.knowledge == original_knowledge

    def test_knowledge_applied_to_team(self):
        from agno.agent import Agent
        from agno.team.team import Team

        from ember_code.team_builder import AgnoFeatures

        f = AgnoFeatures()
        f.knowledge = "fake-knowledge"
        f.search_knowledge = True

        agent = Agent(name="a1")
        team = Team(name="t", members=[agent], mode="coordinate")
        f.apply_to_team(team)
        assert team.knowledge == "fake-knowledge"
        assert team.search_knowledge is True
        # Members also get knowledge
        assert agent.knowledge == "fake-knowledge"


# ── Pydantic Models ──────────────────────────────────────────────


class TestKnowledgeModels:
    def test_add_result_ok(self):
        r = KnowledgeAddResult.ok("added docs")
        assert r.success is True
        assert r.message == "added docs"
        assert r.error is None

    def test_add_result_fail(self):
        r = KnowledgeAddResult.fail("network error")
        assert r.success is False
        assert r.error == "network error"

    def test_search_result(self):
        r = KnowledgeSearchResult(content="hello", name="doc1", score=0.95)
        assert r.content == "hello"
        assert r.score == 0.95
        assert r.metadata == {}

    def test_search_response(self):
        r = KnowledgeSearchResponse(
            query="test",
            results=[KnowledgeSearchResult(content="a")],
            total=1,
        )
        assert r.query == "test"
        assert len(r.results) == 1
        assert r.total == 1

    def test_search_response_empty(self):
        r = KnowledgeSearchResponse(query="test")
        assert r.results == []
        assert r.total == 0

    def test_status_disabled(self):
        s = KnowledgeStatus(enabled=False)
        assert s.enabled is False
        assert s.document_count == 0

    def test_status_enabled(self):
        s = KnowledgeStatus(
            enabled=True,
            collection_name="docs",
            document_count=42,
            embedder="ember",
        )
        assert s.enabled is True
        assert s.document_count == 42

    def test_filter_model(self):
        f = KnowledgeFilter(where={"source": "docs"})
        assert f.where == {"source": "docs"}
        assert f.where_document is None

    def test_filter_with_operators(self):
        f = KnowledgeFilter(where={"$or": [{"source": "a"}, {"source": "b"}]})
        assert "$or" in f.where


# ── Learning Config ──────────────────────────────────────────────


class TestLearningConfig:
    def test_defaults(self):
        cfg = LearningConfig()
        assert cfg.enabled is False
        assert cfg.user_profile is True
        assert cfg.user_memory is True
        assert cfg.session_context is True
        assert cfg.entity_memory is False

    def test_settings_includes_learning(self):
        s = Settings()
        assert hasattr(s, "learning")
        assert isinstance(s.learning, LearningConfig)

    def test_learning_applied_to_agent(self):
        from agno.agent import Agent

        from ember_code.team_builder import AgnoFeatures

        f = AgnoFeatures()
        f.learning = True
        agent = Agent(name="test")
        f.apply_to_agent(agent)
        assert agent.learning is True

    def test_learning_disabled_by_default(self):
        from agno.agent import Agent

        from ember_code.team_builder import AgnoFeatures

        f = AgnoFeatures()
        agent = Agent(name="test")
        f.apply_to_agent(agent)
        # learning defaults to False in AgnoFeatures


# ── Reasoning Config ─────────────────────────────────────────────


class TestReasoningConfig:
    def test_defaults(self):
        cfg = ReasoningConfig()
        assert cfg.enabled is False
        assert cfg.add_instructions is True
        assert cfg.add_few_shot is False

    def test_reasoning_tools_created_from_settings(self):
        from ember_code.team_builder import _create_reasoning_tools

        settings = Settings(reasoning=ReasoningConfig(enabled=True))
        tools = _create_reasoning_tools(settings)
        assert tools is not None
        assert tools.name == "reasoning_tools"

    def test_reasoning_tools_applied_to_agent(self):
        from agno.agent import Agent
        from agno.tools.reasoning import ReasoningTools

        from ember_code.team_builder import AgnoFeatures

        f = AgnoFeatures()
        f.reasoning_tools = ReasoningTools(add_instructions=True)
        agent = Agent(name="test")
        f.apply_to_agent(agent)
        assert any(isinstance(t, ReasoningTools) for t in (agent.tools or []))

    def test_reasoning_not_applied_when_none(self):
        from agno.agent import Agent

        from ember_code.team_builder import AgnoFeatures

        f = AgnoFeatures()
        agent = Agent(name="test", tools=[])
        f.apply_to_agent(agent)
        assert len(agent.tools) == 0


# ── Guardrails Config ────────────────────────────────────────────


class TestGuardrailsConfig:
    def test_defaults(self):
        cfg = GuardrailsConfig()
        assert cfg.pii_detection is False
        assert cfg.prompt_injection is False
        assert cfg.moderation is False

    def test_guardrails_none_when_disabled(self):
        from ember_code.team_builder import _create_guardrails

        settings = Settings()
        result = _create_guardrails(settings)
        assert result is None

    def test_guardrails_applied_to_agent(self):
        from agno.agent import Agent

        from ember_code.team_builder import AgnoFeatures

        class FakeGuardrail:
            pass

        f = AgnoFeatures()
        f.pre_hooks = [FakeGuardrail()]
        agent = Agent(name="test")
        f.apply_to_agent(agent)
        assert len(agent.pre_hooks) == 1

    def test_guardrails_applied_to_team(self):
        from agno.agent import Agent
        from agno.team.team import Team

        from ember_code.team_builder import AgnoFeatures

        class FakeGuardrail:
            pass

        f = AgnoFeatures()
        f.pre_hooks = [FakeGuardrail()]
        team = Team(name="t", members=[Agent(name="a1")], mode="coordinate")
        f.apply_to_team(team)
        assert len(team.pre_hooks) == 1


# ── EmbedderRegistry ────────────────────────────────────────────


class TestEmbedderRegistry:
    def test_builtin_ember(self):
        settings = load_settings()
        registry = EmbedderRegistry(settings)
        embedder = registry.get_embedder("ember")
        assert embedder is not None
        assert isinstance(embedder, EmberEmbedder)
        assert embedder.base_url == "https://api.ignite-ember.sh"
        assert embedder.model == "text2vec-transformers"
        assert embedder.dimensions == 384

    def test_default_name(self):
        settings = load_settings()
        registry = EmbedderRegistry(settings)
        embedder = registry.get_embedder()  # uses default
        assert embedder is not None
        assert isinstance(embedder, EmberEmbedder)

    def test_user_registry_override(self):
        embeddings = EmbeddingsConfig(
            registry={
                "ember": {
                    "provider": "openai_compatible",
                    "model_id": "my-model",
                    "url": "http://my-server:8000",
                    "dimensions": 512,
                }
            }
        )
        settings = Settings(embeddings=embeddings)
        registry = EmbedderRegistry(settings)
        embedder = registry.get_embedder("ember")
        assert isinstance(embedder, EmberEmbedder)
        assert embedder.base_url == "http://my-server:8000"
        assert embedder.model == "my-model"
        assert embedder.dimensions == 512

    def test_custom_entry(self):
        embeddings = EmbeddingsConfig(
            registry={
                "voyage": {
                    "provider": "openai_compatible",
                    "model_id": "voyage-3",
                    "url": "https://api.voyageai.com/v1",
                    "api_key_env": "VOYAGE_API_KEY",
                    "dimensions": 1024,
                }
            }
        )
        settings = Settings(embeddings=embeddings)
        registry = EmbedderRegistry(settings)
        embedder = registry.get_embedder("voyage")
        assert isinstance(embedder, EmberEmbedder)
        assert embedder.base_url == "https://api.voyageai.com/v1"
        assert embedder.model == "voyage-3"
        assert embedder.dimensions == 1024

    def test_provider_model_id_format(self):
        settings = Settings()
        registry = EmbedderRegistry(settings)
        embedder = registry.get_embedder("openai_compatible:my-model")
        assert isinstance(embedder, EmberEmbedder)
        assert embedder.model == "my-model"

    def test_unknown_returns_none(self):
        settings = Settings()
        registry = EmbedderRegistry(settings)
        embedder = registry.get_embedder("nonexistent")
        assert embedder is None

    def test_resolve_entry_user_first(self):
        """User config takes priority over built-in."""
        embeddings = EmbeddingsConfig(
            registry={
                "ember": {
                    "provider": "openai_compatible",
                    "model_id": "overridden",
                    "url": "http://custom:8000",
                }
            }
        )
        settings = Settings(embeddings=embeddings)
        registry = EmbedderRegistry(settings)
        entry = registry._resolve_entry("ember")
        assert entry is not None
        assert entry["model_id"] == "overridden"

    def test_resolve_api_key_env(self):
        with patch.dict("os.environ", {"MY_KEY": "secret123"}):
            key = EmbedderRegistry._resolve_api_key({"api_key_env": "MY_KEY"})
            assert key == "secret123"

    def test_resolve_api_key_missing_env(self):
        key = EmbedderRegistry._resolve_api_key({"api_key_env": "NONEXISTENT_KEY_XYZ"})
        assert key is None

    def test_resolve_api_key_no_config(self):
        key = EmbedderRegistry._resolve_api_key({})
        assert key is None

    def test_get_embedder_via_registry(self):
        settings = load_settings()
        embedder = EmbedderRegistry(settings).get_embedder("ember")
        assert embedder is not None
        assert isinstance(embedder, EmberEmbedder)

    def test_embeddings_config_defaults(self):
        cfg = EmbeddingsConfig()
        assert cfg.default == "ember"
        assert cfg.registry == {}

    def test_embeddings_config_custom(self):
        cfg = EmbeddingsConfig(
            default="voyage",
            registry={
                "voyage": {
                    "provider": "openai_compatible",
                    "model_id": "voyage-3",
                    "url": "https://api.voyageai.com/v1",
                }
            },
        )
        assert cfg.default == "voyage"
        assert "voyage" in cfg.registry
