"""Tests for workspace.py — multi-directory workspace support."""

import pytest

from ember_code.core.workspace import WorkspaceManager


class TestWorkspaceManager:
    def test_single_dir(self, tmp_path):
        ws = WorkspaceManager(tmp_path)
        assert ws.all_dirs == [tmp_path.resolve()]
        assert not ws.is_multi
        assert ws.get_context_instructions() == ""
        assert ws.short_label() == ""

    def test_multi_dir(self, tmp_path):
        extra1 = tmp_path / "extra1"
        extra2 = tmp_path / "extra2"
        extra1.mkdir()
        extra2.mkdir()

        ws = WorkspaceManager(tmp_path, [extra1, extra2])
        assert len(ws.all_dirs) == 3
        assert ws.is_multi
        assert ws.short_label() == "+2 dirs"

    def test_single_extra_label(self, tmp_path):
        extra = tmp_path / "extra"
        extra.mkdir()

        ws = WorkspaceManager(tmp_path, [extra])
        assert ws.short_label() == "+1 dir"

    def test_deduplicates_primary(self, tmp_path):
        ws = WorkspaceManager(tmp_path, [tmp_path])
        assert len(ws.all_dirs) == 1
        assert not ws.is_multi

    def test_context_instructions_contain_paths(self, tmp_path):
        extra = tmp_path / "other-project"
        extra.mkdir()

        ws = WorkspaceManager(tmp_path, [extra])
        ctx = ws.get_context_instructions()
        assert "Primary" in ctx
        assert "Additional" in ctx
        assert str(extra.resolve()) in ctx
        assert "absolute paths" in ctx

    def test_raises_on_missing_dir(self, tmp_path):
        missing = tmp_path / "does-not-exist"
        with pytest.raises(ValueError, match="does not exist"):
            WorkspaceManager(tmp_path, [missing])
