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
)
from ember_code.knowledge.embedder import EmberEmbedder
from ember_code.knowledge.embedder_registry import EmbedderRegistry
from ember_code.knowledge.manager import KnowledgeManager, _resolve_collection_name
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
        assert cfg.enabled is True
        assert cfg.collection_name == "ember_knowledge"
        assert cfg.chroma_db_path == "~/.ember/chromadb"
        assert cfg.max_results == 10
        assert cfg.embedder == "local"

    def test_settings_includes_knowledge(self):
        s = Settings()
        assert hasattr(s, "knowledge")
        assert isinstance(s.knowledge, KnowledgeConfig)

    def test_settings_includes_embeddings(self):
        s = Settings()
        assert hasattr(s, "embeddings")
        assert isinstance(s.embeddings, EmbeddingsConfig)
        assert s.embeddings.default == "local"

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


# ── Collection Name Resolution ──────────────────────────────────


class TestResolveCollectionName:
    def test_uses_git_remote(self, tmp_path):
        """When a git repo with a remote exists, hash is based on remote URL."""
        import subprocess

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "git@github.com:user/my-repo.git"],
            cwd=tmp_path,
            capture_output=True,
        )
        name = _resolve_collection_name("ember_knowledge", tmp_path)
        assert name.startswith("ember_knowledge_")
        assert len(name) == len("ember_knowledge_") + 8

        # Same remote URL should produce same hash
        name2 = _resolve_collection_name("ember_knowledge", tmp_path)
        assert name == name2

    def test_different_remotes_differ(self, tmp_path):
        """Different remote URLs produce different collection names."""
        import subprocess

        # Repo A
        repo_a = tmp_path / "a"
        repo_a.mkdir()
        subprocess.run(["git", "init"], cwd=repo_a, capture_output=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "git@github.com:user/repo-a.git"],
            cwd=repo_a,
            capture_output=True,
        )

        # Repo B
        repo_b = tmp_path / "b"
        repo_b.mkdir()
        subprocess.run(["git", "init"], cwd=repo_b, capture_output=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "git@github.com:user/repo-b.git"],
            cwd=repo_b,
            capture_output=True,
        )

        name_a = _resolve_collection_name("ember_knowledge", repo_a)
        name_b = _resolve_collection_name("ember_knowledge", repo_b)
        assert name_a != name_b

    def test_falls_back_to_path_without_git(self, tmp_path):
        """Non-git directories fall back to path-based hash."""
        name = _resolve_collection_name("ember_knowledge", tmp_path)
        assert name.startswith("ember_knowledge_")
        assert len(name) == len("ember_knowledge_") + 8

    def test_different_dirs_differ(self, tmp_path):
        """Different directories produce different collection names."""
        dir_a = tmp_path / "a"
        dir_a.mkdir()
        dir_b = tmp_path / "b"
        dir_b.mkdir()
        name_a = _resolve_collection_name("ember_knowledge", dir_a)
        name_b = _resolve_collection_name("ember_knowledge", dir_b)
        assert name_a != name_b

    def test_preserves_base_name(self, tmp_path):
        name = _resolve_collection_name("my_project", tmp_path)
        assert name.startswith("my_project_")


# ── KnowledgeManager ─────────────────────────────────────────────


class TestKnowledgeManager:
    def test_disabled_returns_none(self):
        settings = Settings(knowledge=KnowledgeConfig(enabled=False))
        manager = KnowledgeManager(settings)
        result = manager.create_knowledge()
        assert result is None

    def test_create_knowledge_disabled(self):
        settings = Settings(knowledge=KnowledgeConfig(enabled=False))
        result = KnowledgeManager(settings).create_knowledge()
        assert result is None

    def test_creates_local_embedder(self):
        cfg = KnowledgeConfig(enabled=True, embedder="local")
        settings = Settings(knowledge=cfg)
        manager = KnowledgeManager(settings)
        embedder = manager._create_embedder(cfg)
        assert embedder is not None

    def test_unknown_embedder_falls_back_to_local(self):
        cfg = KnowledgeConfig(enabled=True, embedder="unknown")
        settings = Settings(knowledge=cfg)
        manager = KnowledgeManager(settings)
        embedder = manager._create_embedder(cfg)
        assert embedder is not None  # falls back to local

    @patch("ember_code.knowledge.manager.KnowledgeManager._create_embedder")
    def test_no_embedder_returns_none(self, mock_create):
        mock_create.return_value = None
        cfg = KnowledgeConfig(enabled=True)
        settings = Settings(knowledge=cfg)
        manager = KnowledgeManager(settings)
        result = manager.create_knowledge()
        assert result is None


# ── Knowledge on Agno objects ─────────────────────────────────────


class TestKnowledgeOnAgno:
    def test_knowledge_applied_to_agent(self):
        from agno.agent import Agent

        agent = Agent(name="test", knowledge="fake-knowledge", search_knowledge=True)
        assert agent.knowledge == "fake-knowledge"
        assert agent.search_knowledge is True

    def test_knowledge_applied_to_team(self):
        from agno.agent import Agent
        from agno.team.team import Team

        agent = Agent(name="a1")
        team = Team(
            name="t",
            members=[agent],
            mode="coordinate",
            knowledge="fake-knowledge",
            search_knowledge=True,
        )
        assert team.knowledge == "fake-knowledge"
        assert team.search_knowledge is True


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

        agent = Agent(name="test", learning=True)
        assert agent.learning is True

    def test_learning_disabled_by_default(self):
        from agno.agent import Agent

        agent = Agent(name="test")
        # learning defaults to False in Agno
        assert not agent.learning


# ── Reasoning Config ─────────────────────────────────────────────


class TestReasoningConfig:
    def test_defaults(self):
        cfg = ReasoningConfig()
        assert cfg.enabled is False
        assert cfg.add_instructions is True
        assert cfg.add_few_shot is False

    def test_reasoning_tools_created_from_settings(self):
        from ember_code.session.core import _create_reasoning_tools

        settings = Settings(reasoning=ReasoningConfig(enabled=True))
        tools = _create_reasoning_tools(settings)
        assert tools is not None
        assert tools.name == "reasoning_tools"

    def test_reasoning_tools_not_created_when_disabled(self):
        from ember_code.session.core import _create_reasoning_tools

        settings = Settings(reasoning=ReasoningConfig(enabled=False))
        tools = _create_reasoning_tools(settings)
        assert tools is None

    def test_reasoning_tools_on_agent(self):
        from agno.agent import Agent
        from agno.tools.reasoning import ReasoningTools

        tools = ReasoningTools(add_instructions=True)
        agent = Agent(name="test", tools=[tools])
        assert any(isinstance(t, ReasoningTools) for t in (agent.tools or []))


# ── Guardrails Config ────────────────────────────────────────────


class TestGuardrailsConfig:
    def test_defaults(self):
        cfg = GuardrailsConfig()
        assert cfg.pii_detection is True
        assert cfg.prompt_injection is False
        assert cfg.moderation is False

    def test_guardrails_created_when_defaults(self):
        from ember_code.session.core import _create_guardrails

        settings = Settings()
        result = _create_guardrails(settings)
        # PII and injection are enabled by default
        assert result is not None
        assert len(result) >= 1

    def test_guardrails_on_agent(self):
        from agno.agent import Agent

        class FakeGuardrail:
            pass

        agent = Agent(name="test", pre_hooks=[FakeGuardrail()])
        assert len(agent.pre_hooks) == 1

    def test_guardrails_on_team(self):
        from agno.agent import Agent
        from agno.team.team import Team

        class FakeGuardrail:
            pass

        team = Team(
            name="t",
            members=[Agent(name="a1")],
            mode="coordinate",
            pre_hooks=[FakeGuardrail()],
        )
        assert len(team.pre_hooks) == 1


# ── EmbedderRegistry ────────────────────────────────────────────


class TestEmbedderRegistry:
    def test_local_default(self):
        settings = Settings()
        registry = EmbedderRegistry(settings)
        embedder = registry.get_embedder()
        assert embedder is not None

    def test_local_explicit(self):
        settings = Settings()
        registry = EmbedderRegistry(settings)
        embedder = registry.get_embedder("local")
        assert embedder is not None

    def test_unknown_falls_back_to_local(self):
        settings = Settings()
        registry = EmbedderRegistry(settings)
        embedder = registry.get_embedder("nonexistent")
        assert embedder is not None  # falls back to local

    def test_embeddings_config_defaults(self):
        cfg = EmbeddingsConfig()
        assert cfg.default == "local"
        assert cfg.registry == {}
