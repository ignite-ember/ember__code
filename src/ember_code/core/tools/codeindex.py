"""CodeIndex tools — semantic code intelligence via Ember Cloud.

These tools are only registered when the user is authenticated with Ember Cloud.
The server resolves org/integration scope from the auth token and maps the git
remote URL to the correct repository. No client-side repository ID resolution needed.

API reference: CodeIndex endpoints at /v1/codeindex/*
"""

import json
import logging
import subprocess
from typing import Any

import httpx
from agno.tools import Toolkit

logger = logging.getLogger(__name__)


def _get_git_remote(project_dir: str | None = None) -> str | None:
    """Get the git remote URL for the current project.

    Returns None if not in a git repo or no origin remote.
    """
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            cwd=project_dir,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception as exc:
        logger.debug("Failed to get git remote: %s", exc)
        pass
    return None


class CodeIndexTools(Toolkit):
    """Semantic code intelligence powered by Ember Cloud's CodeIndex.

    Provides semantic search, similarity lookup, item details, reference
    graph traversal, and folder tree browsing across indexed repositories.

    The server resolves the repository from the git remote URL sent with
    each request — no client-side repository ID resolution needed.
    """

    def __init__(
        self,
        server_url: str,
        access_token: str,
        project_dir: str | None = None,
    ):
        super().__init__(name="codeindex")
        self._server_url = server_url.rstrip("/")
        self._access_token = access_token
        self._remote_url = _get_git_remote(project_dir)
        self._client: httpx.AsyncClient | None = None

        self.register(self.codeindex_search)
        self.register(self.codeindex_similar)
        self.register(self.codeindex_item)
        self.register(self.codeindex_references)
        self.register(self.codeindex_tree)
        self.register(self.codeindex_tags)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._server_url,
                headers={"Authorization": f"Bearer {self._access_token}"},
                timeout=30.0,
            )
        return self._client

    def _check_remote(self) -> str | None:
        """Return an error message if no git remote is available."""
        if self._remote_url is None:
            return self._json_result(
                {
                    "error": "No git remote found. CodeIndex requires a git repository "
                    "with an origin remote. Use local search tools (Grep, Glob) instead."
                }
            )
        return None

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        """Make an authenticated request to the CodeIndex API."""
        client = self._get_client()
        try:
            response = await client.request(method, path, **kwargs)
            if response.status_code == 401:
                return {"error": "Authentication expired. Run /login to reconnect."}
            if response.status_code == 404:
                return {"error": "Repository not indexed in CodeIndex. Use local search instead."}
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "a few seconds")
                return {"error": f"Rate limited. Retry after {retry_after}."}
            if response.status_code == 503:
                return {"error": "CodeIndex unavailable. Try again later or use local search."}
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.warning("CodeIndex request failed: %s", e)
            return {"error": f"CodeIndex request failed: {e.response.status_code}"}
        except httpx.RequestError as e:
            logger.warning("CodeIndex connection error: %s", e)
            return {"error": "Could not connect to Ember Cloud. Falling back to local search."}

    def _json_result(self, data: dict) -> str:
        return json.dumps(data, indent=2)

    # ── Tools ─────────────────────────────────────────────────────

    async def codeindex_search(
        self,
        query: str,
        item_type: str = "file",
        name: str = "",
        file_extension: str = "",
        tags: list[str] | None = None,
        limit: int = 20,
    ) -> str:
        """Semantic code search across the current repository's indexed codebase.

        Combines vector similarity with filters to find relevant code. Use this
        when you need to find files, classes, or functions by what they do rather
        than exact name matching.

        Args:
            query: Natural language description of what you're looking for.
                   Examples: "authentication middleware that validates JWT tokens",
                   "database connection pooling", "error retry logic with backoff"
            item_type: Filter by item type: "file", "entity", or "folder". Default "file".
            name: Glob pattern to filter by name. Examples: "*auth*", "*.service.*"
            file_extension: Filter by file extension without dot. Examples: "py", "ts", "go"
            tags: List of tags to filter by (all must match). Available tags:
                  - type:file, type:folder, type:entity — item type
                  - type:code, type:docs — file kind (code vs documentation)
                  - entity_type:<type> — entity kind, e.g. entity_type:class,
                    entity_type:function, entity_type:method, entity_type:module
                  Examples: ["type:entity", "entity_type:class"]
            limit: Max results to return (default 20).

        Returns:
            JSON with matching items including file paths, summaries, relevance scores,
            and analysis sections. Each result includes a 'sections' dict with
            type-specific analysis:
              - Entity sections: summary, quality_assessment, security_analysis,
                issues_and_concerns, testing_status
              - File sections: purpose_and_functionality, architecture_and_design,
                code_quality, security, issues_and_technical_debt,
                testing_and_reliability, dependencies_and_impact, recommendations
              - Folder sections: module_purpose, organization_and_structure,
                architectural_assessment, quality_patterns, security_posture,
                common_issues, testing_and_reliability, module_health_score,
                recommendations
        """
        if err := self._check_remote():
            return err

        body: dict[str, Any] = {
            "query": query,
            "remote_url": self._remote_url,
            "item_type": item_type,
            "limit": limit,
        }
        if name:
            body["name"] = name
        if file_extension:
            body["file_extension"] = file_extension
        if tags:
            if len(tags) == 1:
                body["tag_filter"] = {"tag": tags[0]}
            else:
                body["tag_filter"] = {"all": [{"tag": t} for t in tags]}

        result = await self._request("POST", "/v1/codeindex/search", json=body)
        return self._json_result(result)

    async def codeindex_similar(
        self, item_id: str, item_type: str = "file", limit: int = 10
    ) -> str:
        """Find code items semantically similar to a given item.

        Use this after finding an interesting file or entity to discover related
        code — implementations of similar patterns, related modules, or files
        that solve analogous problems.

        Args:
            item_id: The UUID of the item to find similar items for (from a previous search result).
            item_type: Filter results by type: "file", "entity", or "folder". Default "file".
            limit: Max results to return (default 10).

        Returns:
            JSON with semantically similar items, ordered by similarity.
        """
        if err := self._check_remote():
            return err

        body: dict[str, Any] = {
            "item_id": item_id,
            "remote_url": self._remote_url,
            "item_type": item_type,
            "limit": limit,
        }
        result = await self._request("POST", "/v1/codeindex/similar", json=body)
        return self._json_result(result)

    async def codeindex_item(self, item_id: str) -> str:
        """Get full details for a specific indexed item.

        Returns the item's content, AI-generated summary, code chunks,
        and bidirectional references (imports, calls, extends, etc.).

        Use this after a search to get the complete picture of a file or entity
        before deciding whether to read the actual source file.

        Args:
            item_id: The UUID of the item (from a previous search or tree result).

        Returns:
            JSON with item content, summary, chunks, and reference graph.
        """
        if err := self._check_remote():
            return err

        result = await self._request(
            "GET",
            f"/v1/codeindex/items/{item_id}",
            params={"remote_url": self._remote_url},
        )
        return self._json_result(result)

    async def codeindex_references(self, item_id: str) -> str:
        """Get the reference graph for a specific item.

        Returns incoming and outgoing references: what this item imports/calls/extends,
        and what imports/calls/extends it. Each reference includes relationship type
        (IMPORTS, CALLS, EXTENDS, CONTAINS, DECORATED_BY, TYPES_AS, DEPENDS_ON).

        Use this to understand the blast radius before refactoring — which files
        and entities depend on the thing you're about to change.

        Args:
            item_id: The UUID of the item (from a previous search or tree result).

        Returns:
            JSON with document_references (outgoing) and referenced_by (incoming),
            each with relationship tags.
        """
        if err := self._check_remote():
            return err

        result = await self._request(
            "GET",
            f"/v1/codeindex/items/{item_id}/references",
            params={"remote_url": self._remote_url},
        )
        return self._json_result(result)

    async def codeindex_tree(
        self,
        parent_id: str = "",
        item_type: str = "",
        name: str = "",
        query: str = "",
        limit: int = 50,
    ) -> str:
        """Browse the indexed folder/file hierarchy of the repository.

        Without parent_id, returns root-level items. With parent_id, returns
        children of that folder. Can optionally filter by type, name pattern,
        or combine with a semantic search query.

        Use this to explore the high-level structure of an indexed repository
        or to navigate into specific modules.

        Args:
            parent_id: UUID of the parent folder to browse into. Empty for root level.
            item_type: Filter by type: "file", "entity", "folder", or empty for all.
            name: Glob pattern to filter by name. Examples: "*service*", "*.py"
            query: Optional semantic search query to combine with tree browsing.
            limit: Max results to return (default 50).

        Returns:
            JSON with folder/file tree items including names, types, and summaries.
        """
        if err := self._check_remote():
            return err

        body: dict[str, Any] = {
            "remote_url": self._remote_url,
            "limit": limit,
        }
        if parent_id:
            body["parent_id"] = parent_id
        if item_type:
            body["item_type"] = item_type
        if name:
            body["name"] = name
        if query:
            body["query"] = query

        result = await self._request("POST", "/v1/codeindex/tree", json=body)
        return self._json_result(result)

    async def codeindex_tags(self, commit_id: str = "") -> str:
        """Get all available tags for the current repository.

        Returns the complete set of tags that can be used with `codeindex_search`
        to filter results. Tags are scoped to a specific commit (defaults to the
        latest indexed commit). Includes:
          - domain_tags: project-specific domain tags (e.g., "authentication",
            "payments", "api") — these are unique to this repository
          - concerns: project-specific concern tags (e.g., "error-handling",
            "logging", "validation")
          - system_tags: fixed item type tags (type:file, type:entity, etc.)
          - quality_tags: quality assessment tags with possible values
            (e.g., "security:secure|minor-issues|major-issues|critical")

        Use domain and concern tags with the "domain:" and "concern:" prefixes
        in codeindex_search: tags=["domain:authentication", "security:critical"]

        Args:
            commit_id: Optional commit SHA. Defaults to the latest indexed commit.

        Returns:
            JSON with domain_tags, concerns, system_tags, and quality_tags arrays.
        """
        if err := self._check_remote():
            return err

        params: dict[str, str] = {"remote_url": self._remote_url or ""}
        if commit_id:
            params["commit_id"] = commit_id

        result = await self._request(
            "GET",
            "/v1/codeindex/tags",
            params=params,
        )
        return self._json_result(result)

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
