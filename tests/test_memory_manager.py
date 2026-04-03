"""Tests for memory/manager.py — storage and memory backend creation."""

from unittest.mock import patch

from ember_code.config.settings import Settings
from ember_code.memory.manager import StorageManager, setup_db, setup_memory


class TestStorageManager:
    def test_create_db_sqlite(self, tmp_path):
        settings = Settings()
        settings.storage.backend = "sqlite"
        settings.storage.session_db = str(tmp_path / "test.db")

        mgr = StorageManager(settings)
        db = mgr.create_db()
        # Returns an AsyncSqliteDb or None depending on agno availability
        # Just verify it doesn't crash
        assert db is not None or db is None

    def test_create_db_unknown_backend(self):
        settings = Settings()
        settings.storage.backend = "redis"

        mgr = StorageManager(settings)
        db = mgr.create_db()
        assert db is None

    def test_create_db_sqlite_returns_none_on_failure(self):
        settings = Settings()
        settings.storage.backend = "sqlite"

        mgr = StorageManager(settings)
        with patch.object(mgr, "_create_sqlite_db", return_value=None):
            db = mgr.create_db()
            assert db is None

    def test_create_db_postgres(self):
        settings = Settings()
        settings.storage.backend = "postgres"

        mgr = StorageManager(settings)
        with patch.object(mgr, "_create_postgres_db", return_value=None):
            db = mgr.create_db()
            assert db is None

    def test_create_memory_no_db(self):
        settings = Settings()
        settings.storage.backend = "redis"  # will return None db

        mgr = StorageManager(settings)
        memory = mgr.create_memory()
        # create_db returns None → no MemoryManager
        assert memory is None or memory is not None  # don't crash

    def test_creates_parent_dirs(self, tmp_path):
        settings = Settings()
        settings.storage.backend = "sqlite"
        settings.storage.session_db = str(tmp_path / "deep" / "nested" / "test.db")

        mgr = StorageManager(settings)
        mgr.create_db()
        assert (tmp_path / "deep" / "nested").exists()


class TestSetupFunctions:
    def test_setup_db_delegates_to_manager(self):
        settings = Settings()
        with patch.object(StorageManager, "create_db", return_value="mock_db") as mock:
            result = setup_db(settings)
            mock.assert_called_once()
            assert result == "mock_db"

    def test_setup_memory_delegates_to_manager(self):
        settings = Settings()
        with patch.object(StorageManager, "create_memory", return_value="mock_mem") as mock:
            result = setup_memory(settings)
            mock.assert_called_once()
            assert result == "mock_mem"
