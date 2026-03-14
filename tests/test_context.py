"""Tests for utils/context.py."""

from ember_code.utils.context import load_project_context


class TestLoadProjectContext:
    def test_loads_existing_file(self, tmp_path):
        (tmp_path / "ember.md").write_text("hello context")
        result = load_project_context(tmp_path)
        assert result == "hello context"

    def test_returns_empty_for_missing(self, tmp_path):
        result = load_project_context(tmp_path)
        assert result == ""

    def test_custom_filename(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("Custom instructions.\n")
        result = load_project_context(tmp_path, project_file="CLAUDE.md")
        assert "Custom instructions" in result

    def test_default_filename_is_ember_md(self, tmp_path):
        (tmp_path / "ember.md").write_text("# Project\nThis is the project context.\n")
        result = load_project_context(tmp_path)
        assert "Project" in result
