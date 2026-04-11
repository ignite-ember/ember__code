"""Tests for project initialization (init.py)."""

import json
import stat
from pathlib import Path
from unittest.mock import patch

from ember_code.init import BUILT_IN_HOOKS, initialize_project

# All tests patch Path.home() so that ~/.ember/ writes go to tmp_path
# instead of the real home directory.


def _patch_home(tmp_path):
    """Return a patch that redirects Path.home() to tmp_path / 'home'."""
    fake_home = tmp_path / "home"
    fake_home.mkdir(exist_ok=True)
    return patch.object(Path, "home", return_value=fake_home)


class TestInitializeProject:
    def test_creates_marker_file(self, tmp_path):
        with _patch_home(tmp_path):
            initialize_project(tmp_path)
            assert (tmp_path / "home" / ".ember" / ".initialized").exists()

    def test_returns_true_on_first_run(self, tmp_path):
        with _patch_home(tmp_path):
            assert initialize_project(tmp_path) is True

    def test_returns_false_on_second_run(self, tmp_path):
        with _patch_home(tmp_path):
            initialize_project(tmp_path)
            assert initialize_project(tmp_path) is False

    def test_never_runs_again_after_marker(self, tmp_path):
        with _patch_home(tmp_path):
            initialize_project(tmp_path)
            # Delete project hooks but keep marker in ~/.ember/
            hooks = tmp_path / ".ember" / "hooks"
            if hooks.exists():
                import shutil

                shutil.rmtree(hooks)

            # Second run should not recreate anything
            initialize_project(tmp_path)
            assert not (tmp_path / ".ember" / "hooks").exists()

    def test_creates_ember_directory(self, tmp_path):
        with _patch_home(tmp_path):
            initialize_project(tmp_path)
            assert (tmp_path / ".ember").is_dir()

    def test_existing_ember_dir_not_destroyed(self, tmp_path):
        ember_dir = tmp_path / ".ember"
        ember_dir.mkdir()
        (ember_dir / "custom.txt").write_text("keep me")

        with _patch_home(tmp_path):
            initialize_project(tmp_path)
            assert (ember_dir / "custom.txt").read_text() == "keep me"


class TestAgentCopy:
    def test_copies_builtin_agents(self, tmp_path):
        import ember_code.init as init_mod

        original = init_mod.PACKAGE_ROOT

        fake_root = tmp_path / "fake_root"
        fake_root.mkdir()
        agents_dir = fake_root / "agents"
        agents_dir.mkdir()
        (agents_dir / "editor.md").write_text("editor content")
        (agents_dir / "docs.md").write_text("docs content")

        init_mod.PACKAGE_ROOT = fake_root
        try:
            project = tmp_path / "project"
            project.mkdir()
            with _patch_home(tmp_path):
                initialize_project(project)

            copied = project / ".ember" / "agents"
            assert (copied / "editor.md").exists()
            assert (copied / "docs.md").exists()
            assert (copied / "editor.md").read_text() == "editor content"
        finally:
            init_mod.PACKAGE_ROOT = original

    def test_does_not_overwrite_existing_agents(self, tmp_path):
        import ember_code.init as init_mod

        original = init_mod.PACKAGE_ROOT

        fake_root = tmp_path / "fake_root"
        (fake_root / "agents").mkdir(parents=True)
        (fake_root / "agents" / "editor.md").write_text("builtin version")
        (fake_root / "skills").mkdir()

        init_mod.PACKAGE_ROOT = fake_root
        try:
            project = tmp_path / "project"
            project.mkdir()
            agents_dir = project / ".ember" / "agents"
            agents_dir.mkdir(parents=True)
            (agents_dir / "editor.md").write_text("user version")

            with _patch_home(tmp_path):
                initialize_project(project)
            assert (agents_dir / "editor.md").read_text() == "user version"
        finally:
            init_mod.PACKAGE_ROOT = original


class TestSkillCopy:
    def test_copies_builtin_skills(self, tmp_path):
        import ember_code.init as init_mod

        original = init_mod.PACKAGE_ROOT

        fake_root = tmp_path / "fake_root"
        (fake_root / "agents").mkdir(parents=True)
        skills_dir = fake_root / "skills"
        (skills_dir / "commit").mkdir(parents=True)
        (skills_dir / "commit" / "SKILL.md").write_text("commit skill")
        (skills_dir / "simplify").mkdir(parents=True)
        (skills_dir / "simplify" / "SKILL.md").write_text("simplify skill")

        init_mod.PACKAGE_ROOT = fake_root
        try:
            project = tmp_path / "project"
            project.mkdir()
            with _patch_home(tmp_path):
                initialize_project(project)

            copied = project / ".ember" / "skills"
            assert (copied / "commit" / "SKILL.md").exists()
            assert (copied / "simplify" / "SKILL.md").exists()
            assert (copied / "commit" / "SKILL.md").read_text() == "commit skill"
        finally:
            init_mod.PACKAGE_ROOT = original

    def test_ignores_non_skill_directories(self, tmp_path):
        import ember_code.init as init_mod

        original = init_mod.PACKAGE_ROOT

        fake_root = tmp_path / "fake_root"
        (fake_root / "agents").mkdir(parents=True)
        skills_dir = fake_root / "skills"
        (skills_dir / "broken").mkdir(parents=True)
        (skills_dir / "broken" / "README.md").write_text("not a skill")

        init_mod.PACKAGE_ROOT = fake_root
        try:
            project = tmp_path / "project"
            project.mkdir()
            with _patch_home(tmp_path):
                initialize_project(project)
            assert not (project / ".ember" / "skills" / "broken").exists()
        finally:
            init_mod.PACKAGE_ROOT = original


class TestHookProvisioning:
    def test_writes_hook_scripts(self, tmp_path):
        with _patch_home(tmp_path):
            initialize_project(tmp_path)
        hooks_dir = tmp_path / ".ember" / "hooks"
        for hook in BUILT_IN_HOOKS:
            script = hooks_dir / hook["filename"]
            assert script.exists()
            assert script.stat().st_mode & stat.S_IXUSR  # executable

    def test_registers_hooks_in_settings(self, tmp_path):
        with _patch_home(tmp_path):
            initialize_project(tmp_path)
        # Settings now written to ~/.ember/settings.json
        settings = json.loads((tmp_path / "home" / ".ember" / "settings.json").read_text())
        assert "hooks" in settings
        assert "Stop" in settings["hooks"]
        assert any(h["command"] == ".ember/hooks/test-reminder.sh" for h in settings["hooks"]["Stop"])

    def test_preserves_existing_settings(self, tmp_path):
        home_ember = tmp_path / "home" / ".ember"
        home_ember.mkdir(parents=True)
        (home_ember / "settings.json").write_text(json.dumps({"permissions": {"allow": ["Read"]}}))

        with _patch_home(tmp_path):
            initialize_project(tmp_path)
        settings = json.loads((home_ember / "settings.json").read_text())
        assert settings["permissions"]["allow"] == ["Read"]
        assert "hooks" in settings


class TestEmberMd:
    def test_creates_ember_md(self, tmp_path):
        with _patch_home(tmp_path):
            initialize_project(tmp_path)
        path = tmp_path / "ember.md"
        assert path.exists()
        assert "Project Context" in path.read_text()

    def test_does_not_overwrite_existing_ember_md(self, tmp_path):
        (tmp_path / "ember.md").write_text("my custom context")
        with _patch_home(tmp_path):
            initialize_project(tmp_path)
        assert (tmp_path / "ember.md").read_text() == "my custom context"
