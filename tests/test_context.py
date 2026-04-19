"""Tests for utils/context.py — hierarchical rules loading."""

from ember_code.core.utils.context import (
    load_project_context,
    load_project_rules,
    load_subdirectory_rules,
)


class TestLoadProjectRules:
    def test_loads_ember_md(self, tmp_path):
        (tmp_path / "ember.md").write_text("ember rules")
        assert load_project_rules(tmp_path) == "ember rules"

    def test_loads_claude_md(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("claude rules")
        assert load_project_rules(tmp_path) == "claude rules"

    def test_merges_both_files(self, tmp_path):
        (tmp_path / "ember.md").write_text("ember rules")
        (tmp_path / "CLAUDE.md").write_text("claude rules")
        result = load_project_rules(tmp_path)
        assert "ember rules" in result
        assert "claude rules" in result

    def test_skips_claude_md_when_disabled(self, tmp_path):
        (tmp_path / "ember.md").write_text("ember rules")
        (tmp_path / "CLAUDE.md").write_text("claude rules")
        result = load_project_rules(tmp_path, read_claude_md=False)
        assert "ember rules" in result
        assert "claude rules" not in result

    def test_returns_empty_for_missing(self, tmp_path):
        assert load_project_rules(tmp_path) == ""


class TestLoadSubdirectoryRules:
    def test_collects_subdirectory_rules(self, tmp_path):
        src = tmp_path / "src"
        auth = src / "auth"
        working = auth / "middleware"
        working.mkdir(parents=True)
        (src / "ember.md").write_text("src rules")
        (auth / "ember.md").write_text("auth rules")

        results = load_subdirectory_rules(tmp_path, working)
        assert len(results) == 2
        assert results[0] == ("src", "src rules")
        assert results[1] == ("src/auth", "auth rules")

    def test_collects_claude_md_from_subdirectories(self, tmp_path):
        src = tmp_path / "src"
        working = src / "api"
        working.mkdir(parents=True)
        (src / "CLAUDE.md").write_text("claude src rules")

        results = load_subdirectory_rules(tmp_path, working)
        assert len(results) == 1
        assert results[0] == ("src", "claude src rules")

    def test_merges_both_files_in_subdirectory(self, tmp_path):
        src = tmp_path / "src"
        working = src / "api"
        working.mkdir(parents=True)
        (src / "ember.md").write_text("ember src")
        (src / "CLAUDE.md").write_text("claude src")

        results = load_subdirectory_rules(tmp_path, working)
        assert len(results) == 1
        assert "ember src" in results[0][1]
        assert "claude src" in results[0][1]

    def test_returns_empty_when_no_rules(self, tmp_path):
        working = tmp_path / "src"
        working.mkdir()
        assert load_subdirectory_rules(tmp_path, working) == []

    def test_returns_empty_when_working_dir_is_root(self, tmp_path):
        assert load_subdirectory_rules(tmp_path, tmp_path) == []

    def test_returns_empty_when_working_dir_is_none(self, tmp_path):
        assert load_subdirectory_rules(tmp_path, None) == []

    def test_returns_empty_when_outside_project(self, tmp_path):
        other = tmp_path / "other"
        other.mkdir()
        assert load_subdirectory_rules(tmp_path / "project", other) == []


class TestLoadProjectContext:
    def test_merges_root_rules(self, tmp_path):
        (tmp_path / "ember.md").write_text("root rules")
        result = load_project_context(tmp_path)
        assert "root rules" in result
        assert "Project Rules" in result

    def test_returns_empty_when_no_rules(self, tmp_path):
        assert load_project_context(tmp_path) == ""

    def test_merges_root_and_subdirectory(self, tmp_path):
        (tmp_path / "ember.md").write_text("root rules")
        src = tmp_path / "src"
        src.mkdir()
        (src / "ember.md").write_text("src rules")

        result = load_project_context(tmp_path, working_dir=src)
        assert "root rules" in result
        assert "src rules" in result
        assert "Project Rules" in result
        assert "Directory Rules" in result

    def test_claude_md_at_root(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("claude project rules")
        result = load_project_context(tmp_path)
        assert "claude project rules" in result

    def test_both_files_at_root(self, tmp_path):
        (tmp_path / "ember.md").write_text("ember root")
        (tmp_path / "CLAUDE.md").write_text("claude root")
        result = load_project_context(tmp_path)
        assert "ember root" in result
        assert "claude root" in result

    def test_skips_claude_md_when_disabled(self, tmp_path):
        (tmp_path / "ember.md").write_text("ember root")
        (tmp_path / "CLAUDE.md").write_text("claude root")
        result = load_project_context(tmp_path, read_claude_md=False)
        assert "ember root" in result
        assert "claude root" not in result

    def test_sections_separated_by_divider(self, tmp_path):
        (tmp_path / "ember.md").write_text("root")
        src = tmp_path / "src"
        src.mkdir()
        (src / "ember.md").write_text("src")

        result = load_project_context(tmp_path, working_dir=src)
        assert "---" in result
