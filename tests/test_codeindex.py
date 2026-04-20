"""Tests for tools/codeindex.py — CodeIndex semantic search tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ember_code.core.tools.codeindex import CodeIndexTools, _get_git_remote


class TestGetGitRemote:
    def test_returns_url_from_git(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="https://github.com/org/repo.git\n",
            )
            result = _get_git_remote(str(tmp_path))
            assert result == "https://github.com/org/repo.git"

    def test_returns_none_on_failure(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            result = _get_git_remote(str(tmp_path))
            assert result is None

    def test_strips_whitespace(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="  git@github.com:org/repo.git  \n",
            )
            result = _get_git_remote(str(tmp_path))
            assert result == "git@github.com:org/repo.git"


class TestCodeIndexTools:
    def _make_tools(self):
        return CodeIndexTools(
            server_url="https://api.test.com",
            access_token="test-token",
            project_dir="/tmp/test-project",
        )

    def test_registers_all_functions(self):
        tools = self._make_tools()
        names = set()
        for f in tools.functions.values():
            names.add(f.name)
        for f in tools.async_functions.values():
            names.add(f.name)
        assert "codeindex_search" in names
        assert "codeindex_similar" in names
        assert "codeindex_item" in names
        assert "codeindex_references" in names
        assert "codeindex_tree" in names
        assert "codeindex_tags" in names

    @pytest.mark.asyncio
    async def test_search_requires_remote(self):
        tools = self._make_tools()
        with patch.object(tools, "_check_remote", return_value="No git remote found"):
            result = await tools.codeindex_search("test query")
            assert "No git remote" in result

    @pytest.mark.asyncio
    async def test_search_success(self):
        tools = self._make_tools()
        mock_response = {"items": [{"name": "auth.py", "score": 0.95}]}

        with (
            patch.object(tools, "_check_remote", return_value=None),
            patch.object(tools, "_request", new_callable=AsyncMock, return_value=mock_response),
        ):
            result = await tools.codeindex_search("authentication")
            assert "auth.py" in result

    @pytest.mark.asyncio
    async def test_handles_http_error(self):
        tools = self._make_tools()
        error_response = {"error": "CodeIndex request failed: 500"}

        with (
            patch.object(tools, "_check_remote", return_value=None),
            patch.object(tools, "_request", new_callable=AsyncMock, return_value=error_response),
        ):
            result = await tools.codeindex_search("test")
            assert "error" in result.lower()

    @pytest.mark.asyncio
    async def test_item_success(self):
        tools = self._make_tools()
        mock_response = {"id": "file:src/main.py", "name": "main.py", "type": "file"}

        with (
            patch.object(tools, "_check_remote", return_value=None),
            patch.object(tools, "_request", new_callable=AsyncMock, return_value=mock_response),
        ):
            result = await tools.codeindex_item("file:src/main.py")
            assert "main.py" in result

    @pytest.mark.asyncio
    async def test_tree_success(self):
        tools = self._make_tools()
        mock_response = {"items": [{"name": "src", "type": "directory"}]}

        with (
            patch.object(tools, "_check_remote", return_value=None),
            patch.object(tools, "_request", new_callable=AsyncMock, return_value=mock_response),
        ):
            result = await tools.codeindex_tree()
            assert "src" in result

    @pytest.mark.asyncio
    async def test_search_single_tag(self):
        """Single tag produces a leaf tag_filter."""
        tools = self._make_tools()
        mock_response = {"items": []}

        with (
            patch.object(tools, "_check_remote", return_value=None),
            patch.object(
                tools, "_request", new_callable=AsyncMock, return_value=mock_response
            ) as mock_req,
        ):
            await tools.codeindex_search("auth", tags=["type:entity"])
            body = mock_req.call_args.kwargs["json"]
            assert body["tag_filter"] == {"tag": "type:entity"}

    @pytest.mark.asyncio
    async def test_search_multiple_tags(self):
        """Multiple tags produce an AND tag_filter."""
        tools = self._make_tools()
        mock_response = {"items": []}

        with (
            patch.object(tools, "_check_remote", return_value=None),
            patch.object(
                tools, "_request", new_callable=AsyncMock, return_value=mock_response
            ) as mock_req,
        ):
            await tools.codeindex_search("auth", tags=["type:entity", "entity_type:class"])
            body = mock_req.call_args.kwargs["json"]
            assert body["tag_filter"] == {
                "all": [{"tag": "type:entity"}, {"tag": "entity_type:class"}]
            }

    @pytest.mark.asyncio
    async def test_search_no_tags(self):
        """No tags means no tag_filter in the request body."""
        tools = self._make_tools()
        mock_response = {"items": []}

        with (
            patch.object(tools, "_check_remote", return_value=None),
            patch.object(
                tools, "_request", new_callable=AsyncMock, return_value=mock_response
            ) as mock_req,
        ):
            await tools.codeindex_search("auth")
            body = mock_req.call_args.kwargs["json"]
            assert "tag_filter" not in body

    @pytest.mark.asyncio
    async def test_tags_success(self):
        """codeindex_tags calls GET /v1/codeindex/tags with remote_url."""
        tools = self._make_tools()
        mock_response = {
            "repository_id": "repo-123",
            "domain_tags": ["authentication", "payments"],
            "concerns": ["error-handling"],
            "system_tags": ["type:file", "type:entity"],
            "quality_tags": ["quality:excellent|good|fair|poor"],
        }

        with (
            patch.object(tools, "_check_remote", return_value=None),
            patch.object(
                tools, "_request", new_callable=AsyncMock, return_value=mock_response
            ) as mock_req,
        ):
            result = await tools.codeindex_tags()
            assert "authentication" in result
            assert "payments" in result
            mock_req.assert_called_once_with(
                "GET",
                "/v1/codeindex/tags",
                params={"remote_url": tools._remote_url or ""},
            )

    @pytest.mark.asyncio
    async def test_tags_requires_remote(self):
        """codeindex_tags returns error when no git remote."""
        tools = self._make_tools()
        with patch.object(tools, "_check_remote", return_value="No git remote found"):
            result = await tools.codeindex_tags()
            assert "No git remote" in result
