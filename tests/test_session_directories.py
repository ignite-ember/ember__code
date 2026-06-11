"""Tests for the global session → project-directory registry."""

from __future__ import annotations

from ember_code.core.session.session_directories import SessionDirectoryStore


def test_set_then_get(tmp_path):
    store = SessionDirectoryStore(tmp_path / "sessions.db")
    store.set_dir("sess-a", "/repos/alpha")
    assert store.get_dir("sess-a") == "/repos/alpha"


def test_unknown_session_returns_none(tmp_path):
    store = SessionDirectoryStore(tmp_path / "sessions.db")
    assert store.get_dir("nope") is None


def test_upsert_overwrites(tmp_path):
    store = SessionDirectoryStore(tmp_path / "sessions.db")
    store.set_dir("sess", "/old")
    store.set_dir("sess", "/new")
    assert store.get_dir("sess") == "/new"


def test_empty_session_id_is_noop(tmp_path):
    store = SessionDirectoryStore(tmp_path / "sessions.db")
    store.set_dir("", "/somewhere")
    assert store.get_dir("") is None


def test_survives_reopen(tmp_path):
    db = tmp_path / "sessions.db"
    SessionDirectoryStore(db).set_dir("sess", "/repos/alpha")
    assert SessionDirectoryStore(db).get_dir("sess") == "/repos/alpha"


def test_path_objects_stored_as_strings(tmp_path):
    store = SessionDirectoryStore(tmp_path / "sessions.db")
    store.set_dir("sess", tmp_path)
    assert store.get_dir("sess") == str(tmp_path)
