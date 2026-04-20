"""Tests for session/knowledge_ops.py — knowledge base operations."""

from unittest.mock import MagicMock

import pytest

from ember_code.core.config.settings import Settings
from ember_code.core.session.knowledge_ops import SessionKnowledgeManager


class TestShareEnabled:
    def test_enabled_when_all_conditions_met(self):
        settings = Settings()
        settings.knowledge.enabled = True
        settings.knowledge.share = True
        mgr = SessionKnowledgeManager(knowledge=MagicMock(), settings=settings, project_dir="/tmp")
        assert mgr.share_enabled() is True

    def test_disabled_when_knowledge_none(self):
        settings = Settings()
        settings.knowledge.enabled = True
        settings.knowledge.share = True
        mgr = SessionKnowledgeManager(knowledge=None, settings=settings, project_dir="/tmp")
        assert mgr.share_enabled() is False

    def test_disabled_when_share_false(self):
        settings = Settings()
        settings.knowledge.enabled = True
        settings.knowledge.share = False
        mgr = SessionKnowledgeManager(knowledge=MagicMock(), settings=settings, project_dir="/tmp")
        assert mgr.share_enabled() is False


class TestAdd:
    @pytest.mark.asyncio
    async def test_fails_when_no_knowledge(self):
        settings = Settings()
        mgr = SessionKnowledgeManager(knowledge=None, settings=settings, project_dir="/tmp")
        result = await mgr.add(text="hello")
        assert not result.success
        assert "not enabled" in result.error.lower()

    @pytest.mark.asyncio
    async def test_fails_when_no_content(self):
        settings = Settings()
        mgr = SessionKnowledgeManager(knowledge=MagicMock(), settings=settings, project_dir="/tmp")
        result = await mgr.add()
        assert not result.success

    @pytest.mark.asyncio
    async def test_adds_text_successfully(self):
        knowledge = MagicMock()
        knowledge.insert = MagicMock()

        settings = Settings()
        settings.knowledge.share = False  # skip file sync
        mgr = SessionKnowledgeManager(knowledge=knowledge, settings=settings, project_dir="/tmp")
        result = await mgr.add(text="Some knowledge")
        assert result.success
        knowledge.insert.assert_called_once()


class TestSearch:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_knowledge(self):
        settings = Settings()
        mgr = SessionKnowledgeManager(knowledge=None, settings=settings, project_dir="/tmp")
        result = await mgr.search("test query")
        assert result.total == 0

    @pytest.mark.asyncio
    async def test_returns_results(self):
        doc = MagicMock()
        doc.content = "Found result content"
        doc.name = "doc.py"
        doc.reranking_score = 0.9
        doc.meta_data = {"source": "test"}

        knowledge = MagicMock()
        knowledge.search = MagicMock(return_value=[doc])

        settings = Settings()
        mgr = SessionKnowledgeManager(knowledge=knowledge, settings=settings, project_dir="/tmp")
        result = await mgr.search("test", limit=5)

        assert result.total == 1
        assert result.results[0].name == "test"  # prefers source from metadata


class TestStatus:
    def test_disabled_when_no_knowledge(self):
        settings = Settings()
        mgr = SessionKnowledgeManager(knowledge=None, settings=settings, project_dir="/tmp")
        status = mgr.status()
        assert status.enabled is False

    def test_enabled_with_knowledge(self):
        knowledge = MagicMock()
        knowledge.vector_db = MagicMock()
        knowledge.vector_db._collection.count.return_value = 42

        settings = Settings()
        mgr = SessionKnowledgeManager(knowledge=knowledge, settings=settings, project_dir="/tmp")
        status = mgr.status()

        assert status.enabled is True
        assert status.document_count == 42
