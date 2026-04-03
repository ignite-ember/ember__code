"""Tests for KnowledgeTools — agent-facing knowledge base operations."""

from unittest.mock import AsyncMock, MagicMock

from ember_code.knowledge.models import (
    KnowledgeAddResult,
    KnowledgeSearchResponse,
    KnowledgeSearchResult,
    KnowledgeStatus,
)
from ember_code.tools.knowledge import KnowledgeTools


def _make_mgr():
    """Create a mock SessionKnowledgeManager."""
    mgr = MagicMock()
    mgr.knowledge = MagicMock()
    mgr.search = AsyncMock(return_value=KnowledgeSearchResponse(query="test"))
    mgr.add = AsyncMock(return_value=KnowledgeAddResult.ok("Added."))
    mgr.status = MagicMock(
        return_value=KnowledgeStatus(
            enabled=True,
            collection_name="proj",
            document_count=42,
            embedder="ember",
        )
    )
    return mgr


class TestKnowledgeSearch:
    def test_search_returns_results(self):
        mgr = _make_mgr()
        mgr.search = AsyncMock(
            return_value=KnowledgeSearchResponse(
                query="auth",
                results=[
                    KnowledgeSearchResult(content="JWT tokens", name="auth.md"),
                    KnowledgeSearchResult(content="OAuth flow", name="oauth.md"),
                ],
                total=2,
            )
        )
        tools = KnowledgeTools(knowledge_mgr=mgr)
        result = tools.knowledge_search("auth")
        assert "2 result" in result
        assert "JWT tokens" in result
        assert "OAuth flow" in result

    def test_search_no_results(self):
        mgr = _make_mgr()
        tools = KnowledgeTools(knowledge_mgr=mgr)
        result = tools.knowledge_search("nonexistent")
        assert "No knowledge found" in result

    def test_search_passes_limit(self):
        mgr = _make_mgr()
        tools = KnowledgeTools(knowledge_mgr=mgr)
        tools.knowledge_search("q", limit=3)
        mgr.search.assert_called_once()
        _, kwargs = mgr.search.call_args
        assert kwargs["limit"] == 3


class TestKnowledgeAdd:
    def test_add_success(self):
        mgr = _make_mgr()
        tools = KnowledgeTools(knowledge_mgr=mgr)
        result = tools.knowledge_add("New pattern discovered", source="code review")
        assert "Added" in result
        mgr.add.assert_called_once()

    def test_add_failure(self):
        mgr = _make_mgr()
        mgr.add = AsyncMock(return_value=KnowledgeAddResult.fail("DB error"))
        tools = KnowledgeTools(knowledge_mgr=mgr)
        result = tools.knowledge_add("content")
        assert "Error" in result
        assert "DB error" in result


class TestKnowledgeDelete:
    def test_delete_preview(self):
        mgr = _make_mgr()
        mgr.search = AsyncMock(
            return_value=KnowledgeSearchResponse(
                query="old",
                results=[KnowledgeSearchResult(content="Old entry", name="old.md")],
                total=1,
            )
        )
        tools = KnowledgeTools(knowledge_mgr=mgr)
        result = tools.knowledge_delete("old", confirm=False)
        assert "Old entry" in result
        assert "confirm=True" in result

    def test_delete_no_matches(self):
        mgr = _make_mgr()
        tools = KnowledgeTools(knowledge_mgr=mgr)
        result = tools.knowledge_delete("nonexistent")
        assert "No knowledge entries match" in result

    def test_delete_no_knowledge(self):
        mgr = _make_mgr()
        mgr.knowledge = None
        mgr.search = AsyncMock(
            return_value=KnowledgeSearchResponse(
                query="q",
                results=[KnowledgeSearchResult(content="x", name="x")],
                total=1,
            )
        )
        tools = KnowledgeTools(knowledge_mgr=mgr)
        result = tools.knowledge_delete("q", confirm=True)
        assert "not available" in result


class TestKnowledgeStatus:
    def test_status_enabled(self):
        mgr = _make_mgr()
        tools = KnowledgeTools(knowledge_mgr=mgr)
        result = tools.knowledge_status()
        assert "proj" in result
        assert "42" in result
        assert "ember" in result

    def test_status_disabled(self):
        mgr = _make_mgr()
        mgr.status = MagicMock(return_value=KnowledgeStatus(enabled=False))
        tools = KnowledgeTools(knowledge_mgr=mgr)
        result = tools.knowledge_status()
        assert "disabled" in result
