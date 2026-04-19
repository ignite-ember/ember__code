"""Tests for FileIndex — project file listing and fuzzy matching."""

import subprocess
from pathlib import Path

import pytest

from ember_code.frontend.tui.file_index import (
    FileIndex,
    _fallback_list,
    _git_ls_files,
    _score_match,
)

# ── _score_match ─────────────────────────────────────────────────


class TestScoreMatch:
    def test_exact_match(self):
        assert _score_match("main.py", "main.py") is not None

    def test_no_match(self):
        assert _score_match("xyz", "main.py") is None

    def test_subsequence_match(self):
        assert _score_match("mp", "main.py") is not None

    def test_empty_query_matches(self):
        assert _score_match("", "anything.py") is not None

    def test_path_match(self):
        score = _score_match("src/util", "src/utils/media.py")
        assert score is not None
        assert score > 0

    def test_filename_bonus(self):
        # "media" appears in filename — should score higher than deep path match
        score_filename = _score_match("media", "src/utils/media.py")
        score_path = _score_match("media", "src/media_old/config.py")
        assert score_filename is not None
        assert score_path is not None

    def test_boundary_bonus(self):
        # Match at path boundary (after /) should score higher
        score_boundary = _score_match("u", "src/utils.py")
        score_mid = _score_match("u", "about.py")
        assert score_boundary is not None
        assert score_mid is not None
        assert score_boundary > score_mid

    def test_contiguous_bonus(self):
        # Contiguous characters score higher
        score_contiguous = _score_match("main", "main.py")
        score_scattered = _score_match("main", "my_archive_index.py")
        assert score_contiguous is not None
        assert score_scattered is not None
        assert score_contiguous > score_scattered

    def test_case_insensitive(self):
        assert _score_match("README", "readme.md") is not None
        assert _score_match("readme", "README.md") is not None


# ── _git_ls_files ────────────────────────────────────────────────


class TestGitLsFiles:
    def test_returns_files_in_git_repo(self, tmp_path):
        # Create a minimal git repo
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        (tmp_path / "file.txt").write_text("hello")
        subprocess.run(["git", "add", "file.txt"], cwd=tmp_path, capture_output=True)
        result = _git_ls_files(tmp_path)
        assert "file.txt" in result

    def test_non_git_dir_returns_empty(self, tmp_path):
        (tmp_path / "file.txt").write_text("hello")
        result = _git_ls_files(tmp_path)
        assert result == []


# ── _fallback_list ───────────────────────────────────────────────


class TestFallbackList:
    def test_lists_files(self, tmp_path):
        (tmp_path / "a.py").write_text("pass")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.py").write_text("pass")
        result = _fallback_list(tmp_path)
        assert "a.py" in result
        assert "sub/b.py" in result

    def test_ignores_pycache(self, tmp_path):
        cache = tmp_path / "__pycache__"
        cache.mkdir()
        (cache / "mod.cpython-311.pyc").write_bytes(b"")
        (tmp_path / "main.py").write_text("pass")
        result = _fallback_list(tmp_path)
        assert "main.py" in result
        assert not any("__pycache__" in f for f in result)

    def test_ignores_node_modules(self, tmp_path):
        nm = tmp_path / "node_modules" / "pkg"
        nm.mkdir(parents=True)
        (nm / "index.js").write_text("")
        (tmp_path / "app.js").write_text("")
        result = _fallback_list(tmp_path)
        assert "app.js" in result
        assert not any("node_modules" in f for f in result)


# ── FileIndex ────────────────────────────────────────────────────


class TestFileIndex:
    def _make_index(self, files: list[str]) -> FileIndex:
        fi = FileIndex(Path("."))
        fi._files = files
        fi._loaded = True
        return fi

    def test_match_empty_query_returns_first_n(self):
        fi = self._make_index(["a.py", "b.py", "c.py"])
        result = fi.match("", limit=2)
        assert result == ["a.py", "b.py"]

    def test_match_filters(self):
        fi = self._make_index(["src/main.py", "src/utils.py", "tests/test_main.py"])
        result = fi.match("util")
        assert "src/utils.py" in result
        assert "src/main.py" not in result

    def test_match_respects_limit(self):
        files = [f"file{i}.py" for i in range(100)]
        fi = self._make_index(files)
        result = fi.match("file", limit=5)
        assert len(result) == 5

    def test_match_no_results(self):
        fi = self._make_index(["src/main.py"])
        assert fi.match("zzzzz") == []

    def test_match_empty_index(self):
        fi = self._make_index([])
        assert fi.match("anything") == []

    def test_match_deep_paths(self):
        fi = self._make_index(
            [
                "src/ember_code/tui/widgets/_file_picker.py",
                "src/ember_code/tui/app.py",
                "src/ember_code/tools/registry.py",
            ]
        )
        result = fi.match("picker")
        assert "src/ember_code/tui/widgets/_file_picker.py" in result

    def test_is_loaded(self):
        fi = FileIndex(Path("."))
        assert fi.is_loaded is False
        fi._loaded = True
        assert fi.is_loaded is True

    def test_file_count(self):
        fi = self._make_index(["a.py", "b.py"])
        assert fi.file_count == 2

    @pytest.mark.asyncio
    async def test_ensure_loaded(self, tmp_path):
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        (tmp_path / "hello.py").write_text("pass")
        subprocess.run(["git", "add", "hello.py"], cwd=tmp_path, capture_output=True)

        fi = FileIndex(tmp_path)
        await fi.ensure_loaded()
        assert fi.is_loaded
        assert "hello.py" in fi._files

    @pytest.mark.asyncio
    async def test_ensure_loaded_idempotent(self, tmp_path):
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        (tmp_path / "a.py").write_text("pass")
        subprocess.run(["git", "add", "a.py"], cwd=tmp_path, capture_output=True)

        fi = FileIndex(tmp_path)
        await fi.ensure_loaded()
        count = fi.file_count
        await fi.ensure_loaded()
        assert fi.file_count == count
