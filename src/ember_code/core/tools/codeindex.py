"""CodeIndexTools — agent-facing structured query over the local code index.

The tool takes typed enum args and translates them into chroma where-clauses
internally; agents never write raw chroma queries. Each quality dimension
is a typed enum, each multi-value category is a list of strings; combining
them in one call is exact-match-ANDed across categories and OR-within a
single multi-value category.

Why structured-only (no ``where=`` escape hatch):

- The agent doesn't have to know chroma operators (``$and`` / ``$or`` /
  ``$contains`` / ``$in``) or the ``\\x1f``-bracketed encoding of list
  fields — both stay internal.
- Schema or storage changes don't break prompts; only the tool internals
  move.
- Wrong field values fail fast at the SDK level (enum constraint), not
  silently with empty results.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from agno.tools import Toolkit
from pydantic import BaseModel, Field

from ember_code.core.code_index.enums import (
    CohesionLevel,
    ComplexityLevel,
    CouplingLevel,
    DocumentationLevel,
    IssuesSeverity,
    Kind,
    PerformanceLevel,
    PriorityLevel,
    QualityLevel,
    Relation,
    Section,
    SecurityLevel,
    StabilityLevel,
    TechnicalDebtLevel,
    TestabilityLevel,
    TestingLevel,
)
from ember_code.core.code_index.index import CodeIndex
from ember_code.core.code_index.schema.items import CodeIndexResult

logger = logging.getLogger(__name__)


# ── Tool response envelopes ──────────────────────────────────────────


class ItemsResponse(BaseModel):
    """Response envelope for both ``codeindex_query`` (search / filter)
    and ``codeindex_tree`` (single-item drill-down). The drill-down
    case sets ``total=1`` and the one item carries a populated
    ``references`` map; ``codeindex_query`` never populates references.
    """

    commit: str
    items: list[CodeIndexResult]
    total: int
    truncated: bool = False


class ErrorResponse(BaseModel):
    error: str


# ── Content section filter ───────────────────────────────────────────
#
# The indexer's LLM-summary pass writes ``content`` as
# ``[SECTION:<name>]…[/SECTION]`` blocks, but the concrete section
# names differ per item type (file / entity / folder). Agents pick
# semantic groups via the ``Section`` enum on ``codeindex_query``;
# this map expands each group to the set of concrete names that
# carry that meaning across item types.

_SECTION_ALIASES: dict[Section, frozenset[str]] = {
    Section.SUMMARY: frozenset({"summary", "purpose_and_functionality", "module_purpose"}),
    Section.QUALITY: frozenset({"quality_assessment", "code_quality", "quality_patterns"}),
    Section.SECURITY: frozenset({"security_analysis", "security", "security_posture"}),
    Section.ISSUES: frozenset(
        {"issues_and_concerns", "issues_and_technical_debt", "common_issues"}
    ),
    Section.TESTING: frozenset({"testing_status", "testing_and_reliability"}),
    Section.ARCHITECTURE: frozenset(
        {"architecture_and_design", "organization_and_structure", "architectural_assessment"}
    ),
    Section.DEPENDENCIES: frozenset({"dependencies_and_impact"}),
    Section.RECOMMENDATIONS: frozenset({"recommendations"}),
    Section.HEALTH_SCORE: frozenset({"module_health_score"}),
    Section.ENTITIES: frozenset({"entities"}),
}

_SECTION_RE = re.compile(
    r"\[SECTION:(?P<name>[a-z_]+)\](?P<body>.*?)\[/SECTION\]",
    re.DOTALL,
)
_DEFAULT_SECTIONS: tuple[Section, ...] = (Section.SUMMARY,)


_SUMMARY_NAMES: frozenset[str] = _SECTION_ALIASES[Section.SUMMARY]
_SHORT_SUMMARY_MAX_CHARS = 200


def _shorten_summary(content: str) -> str:
    """Extract the first SUMMARY-group section from ``content`` and
    return its first sentence (or first ``_SHORT_SUMMARY_MAX_CHARS``
    chars, whichever is shorter). Used to give the agent a one-line
    "what this thing does" alongside reference edges. Returns "" if
    the content has no markers or no summary section.
    """
    if not content:
        return ""
    for m in _SECTION_RE.finditer(content):
        if m.group("name") not in _SUMMARY_NAMES:
            continue
        body = m.group("body").strip()
        if not body:
            return ""
        # Take the first sentence — most LLM-generated summaries open
        # with a one-sentence "this does X" before elaborating.
        first_sentence, _, _ = body.partition(". ")
        first_sentence = first_sentence.strip().rstrip(".")
        # Fall back to a hard char cap so a summary written without
        # sentence boundaries still fits.
        if not first_sentence or len(first_sentence) > _SHORT_SUMMARY_MAX_CHARS:
            first_sentence = body[:_SHORT_SUMMARY_MAX_CHARS].rstrip()
        return f"{first_sentence}."
    return ""


def _filter_sections(content: str, sections: tuple[Section, ...]) -> str:
    """Keep only the requested ``[SECTION:…]…[/SECTION]`` blocks.

    ``sections`` carries semantic groups (e.g. ``Section.SECURITY``);
    the alias map resolves each group to the concrete section names
    used at file / entity / folder level. Returns the joined matching
    blocks (newline-separated) in the order they appear in the
    original content. If the content has no section markers, returns
    it unchanged — short docs / non-summarized items don't get
    filtered. If the resolved name set doesn't match anything in the
    content, returns an empty string (agent gets back what's actually
    there, which may be nothing).
    """
    if not content or not sections:
        return content
    wanted: set[str] = set()
    for s in sections:
        wanted |= _SECTION_ALIASES.get(s, frozenset())
    matches = list(_SECTION_RE.finditer(content))
    if not matches:
        return content
    kept = [
        f"[SECTION:{m.group('name')}]{m.group('body')}[/SECTION]"
        for m in matches
        if m.group("name") in wanted
    ]
    return "\n\n".join(kept)


# ── Filter envelopes ──────────────────────────────────────────────────
#
# Two pydantic models hold the structured args while we move them
# from the tool's flat parameter list down to the chroma-side / Python-
# side filter logic. Splitting categorical from list-shaped here keeps
# the where-builder and the post-filter on opposite sides of a clear
# boundary: categoricals can be pushed down to chroma, list-shaped
# can't (chroma's metadata ``where`` lacks ``$contains``).


class _CategoricalFilters(BaseModel):
    """Single-value (or ``$in`` list) filters that push down to chroma.

    Every field is independently optional — ``None`` means "no filter
    on this dimension". A list value on any quality field means
    "match any of these values" (``$in``).
    """

    # Scope
    kind: Kind | None = None
    type: str | None = None
    entity_type: str | list[str] | None = None
    file_extension: str | None = None
    path_prefix: str | None = None
    needs_refactoring: bool | None = None

    # Quality categoricals
    quality: QualityLevel | list[QualityLevel] | None = None
    complexity: ComplexityLevel | list[ComplexityLevel] | None = None
    security: SecurityLevel | list[SecurityLevel] | None = None
    testing: TestingLevel | list[TestingLevel] | None = None
    testability: TestabilityLevel | list[TestabilityLevel] | None = None
    documentation: DocumentationLevel | list[DocumentationLevel] | None = None
    performance: PerformanceLevel | list[PerformanceLevel] | None = None
    issues: IssuesSeverity | list[IssuesSeverity] | None = None
    maintainability: QualityLevel | list[QualityLevel] | None = None
    architecture: QualityLevel | list[QualityLevel] | None = None
    technical_debt: TechnicalDebtLevel | list[TechnicalDebtLevel] | None = None
    cohesion: CohesionLevel | list[CohesionLevel] | None = None
    coupling: CouplingLevel | list[CouplingLevel] | None = None
    stability: StabilityLevel | list[StabilityLevel] | None = None
    priority: PriorityLevel | list[PriorityLevel] | None = None


# Names of the quality categoricals — used by the where-builder loop
# below so adding a new dimension doesn't require a second hand-edit.
# Scope and ``needs_refactoring`` have field-specific shape so they're
# handled explicitly outside this list.
_CATEGORICAL_QUALITY_FIELDS: tuple[str, ...] = (
    "quality",
    "complexity",
    "security",
    "testing",
    "testability",
    "documentation",
    "performance",
    "issues",
    "maintainability",
    "architecture",
    "technical_debt",
    "cohesion",
    "coupling",
    "stability",
    "priority",
)


class _ListFilters(BaseModel):
    """Multi-value categories. Applied as a Python post-filter after
    chroma narrows on categoricals — chroma metadata ``where`` has no
    ``$contains`` operator, and exploding to one row per value would
    triple the index.
    """

    vulnerabilities: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    domain: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    layers: list[str] = Field(default_factory=list)
    patterns: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    file_issues: list[str] = Field(default_factory=list)

    @property
    def has_any(self) -> bool:
        """True iff any list category carries at least one value."""
        return any(getattr(self, f) for f in type(self).model_fields)

    def matches(self, item: CodeIndexResult) -> bool:
        """True iff ``item`` matches every non-empty list filter.

        Cross-category is AND (every filter that's set must hit); within
        one category any value matching the item's list counts as a hit
        (OR within).
        """
        for field in type(self).model_fields:
            wanted = getattr(self, field)
            if not wanted:
                continue
            present = set(getattr(item, field, []) or [])
            if not present.intersection(wanted):
                return False
        return True


class CodeIndexTools(Toolkit):
    """Single-tool structured query surface over the per-commit code index.

    Args:
        project_dir: project root used to derive the on-disk path.
            Defaults to ``cwd``.
        data_dir: ember root, defaults to ``~/.ember``.
        index: pre-built :class:`CodeIndex` (used by tests / advanced
            callers). When provided, ``project_dir`` and ``data_dir``
            are ignored.
    """

    def __init__(
        self,
        *,
        project_dir: str | Path | None = None,
        data_dir: str | Path = "~/.ember",
        index: CodeIndex | None = None,
        **kwargs: Any,
    ):
        super().__init__(name="codeindex", **kwargs)
        self._explicit_index = index
        self._project_dir = Path(str(project_dir)) if project_dir else Path.cwd()
        self._data_dir = data_dir
        self.register(self.codeindex_query)
        self.register(self.codeindex_tree)

    @staticmethod
    def _json(data: Any) -> str:
        if isinstance(data, BaseModel):
            return data.model_dump_json(indent=2)
        return json.dumps(data, indent=2, default=str)

    @staticmethod
    def _telemetry_log(record: dict[str, Any]) -> None:
        """Append a query/response record to the eval telemetry log if enabled.

        Activated via the ``EMBER_EVAL_TELEMETRY_PATH`` env var. Used by
        the eval runner so reports can show what chroma actually
        returned and what the agent fed back into the conversation.
        No-op when the var is unset.
        """
        import os

        path = os.environ.get("EMBER_EVAL_TELEMETRY_PATH")
        if not path:
            return
        try:
            with open(path, "a") as fh:
                fh.write(json.dumps(record, default=str) + "\n")
        except Exception:
            # Best-effort: never break a real call because the log
            # file is unavailable.
            pass

    def _ensure_index(self) -> CodeIndex:
        if self._explicit_index is None:
            self._explicit_index = CodeIndex(project=self._project_dir, data_dir=self._data_dir)
        return self._explicit_index

    async def close(self) -> None:
        if self._explicit_index is not None:
            await self._explicit_index.close()

    # ── The tool ──────────────────────────────────────────────────────

    async def codeindex_query(
        self,
        # ── what you're searching ──
        query_text: str | None = None,
        # ── direct fetch ──
        ids: list[str] | None = None,
        # ── structural scope ──
        kind: Kind | None = None,
        type: str | None = None,
        entity_type: str | list[str] | None = None,
        file_extension: str | None = None,
        path_prefix: str | None = None,
        # ── quality categoricals (single value or list = OR) ──
        quality: QualityLevel | list[QualityLevel] | None = None,
        complexity: ComplexityLevel | list[ComplexityLevel] | None = None,
        security: SecurityLevel | list[SecurityLevel] | None = None,
        testing: TestingLevel | list[TestingLevel] | None = None,
        testability: TestabilityLevel | list[TestabilityLevel] | None = None,
        documentation: DocumentationLevel | list[DocumentationLevel] | None = None,
        performance: PerformanceLevel | list[PerformanceLevel] | None = None,
        issues: IssuesSeverity | list[IssuesSeverity] | None = None,
        maintainability: QualityLevel | list[QualityLevel] | None = None,
        architecture: QualityLevel | list[QualityLevel] | None = None,
        technical_debt: TechnicalDebtLevel | list[TechnicalDebtLevel] | None = None,
        cohesion: CohesionLevel | list[CohesionLevel] | None = None,
        coupling: CouplingLevel | list[CouplingLevel] | None = None,
        stability: StabilityLevel | list[StabilityLevel] | None = None,
        priority: PriorityLevel | list[PriorityLevel] | None = None,
        needs_refactoring: bool | None = None,
        # ── list-shaped categories (each a list — OR within) ──
        vulnerabilities: list[str] | None = None,
        frameworks: list[str] | None = None,
        domain: list[str] | None = None,
        concerns: list[str] | None = None,
        layers: list[str] | None = None,
        patterns: list[str] | None = None,
        keywords: list[str] | None = None,
        file_issues: list[str] | None = None,
        # ── output control ──
        sections: list[Section] | None = None,
        limit: int = 20,
        commit: str | None = None,
    ) -> str:
        """Search / filter the code index — returns a list of items.

        This tool **never returns reference data**. To explore an
        item's edges (calls, called_by, imports, …), use
        ``codeindex_tree`` after you've identified the uuid here.

        Args:
            query_text: natural-language search ("auth flow", "memory leak").
                When set, runs semantic search; otherwise runs filter-only fetch.
            ids: fetch specific item ids directly. Mutually exclusive with
                ``query_text``.
            kind: ``"code"`` or ``"docs"``.
            type: ``"file"``, ``"folder"``, or ``"entity"``.
            entity_type: ``"function"``, ``"class"``, ``"section"``, etc.
                Pass a list for OR.
            file_extension: ``".py"``, ``".ts"``, etc.
            path_prefix: path scope filter (matches via ``$contains`` for now —
                future versions may switch to a true prefix once chroma supports it).
            quality / complexity / security / testing / testability /
            documentation / performance / issues / maintainability /
            architecture / technical_debt / cohesion / coupling / stability /
            priority: each takes one enum value or a list (list = OR).
            needs_refactoring: bool filter.
            vulnerabilities / frameworks / domain / concerns / layers /
            patterns / keywords / file_issues: lists. Multiple values OR
            within one category. Cross-category is AND.
            sections: which content sections to return per item.
                Pass semantic groups from the ``Section`` enum
                (``summary``, ``quality``, ``security``, ``issues``,
                ``testing``, ``architecture``, ``dependencies``,
                ``recommendations``, ``health_score``, ``entities``).
                Each group resolves to the concrete section names for
                that item type. Default is ``[summary]`` (~5× smaller
                responses).
            limit: max results. Default 20.
            commit: commit SHA. Defaults to current head.

        Returns: JSON list response (``ItemsResponse`` shape — items
            without reference data; use ``codeindex_tree`` for that).
        """
        # Snapshot the inputs before any normalization so the telemetry
        # log shows exactly what the agent passed in. Filtering out
        # ``None``/empty defaults keeps the log compact.
        import time as _time

        _t0 = _time.monotonic()
        _telemetry_args = {
            k: v
            for k, v in {
                "query_text": query_text,
                "ids": ids,
                "kind": kind,
                "type": type,
                "entity_type": entity_type,
                "file_extension": file_extension,
                "path_prefix": path_prefix,
                "quality": quality,
                "complexity": complexity,
                "security": security,
                "testing": testing,
                "testability": testability,
                "documentation": documentation,
                "performance": performance,
                "issues": issues,
                "maintainability": maintainability,
                "architecture": architecture,
                "technical_debt": technical_debt,
                "cohesion": cohesion,
                "coupling": coupling,
                "stability": stability,
                "priority": priority,
                "needs_refactoring": needs_refactoring,
                "vulnerabilities": vulnerabilities,
                "frameworks": frameworks,
                "domain": domain,
                "concerns": concerns,
                "layers": layers,
                "patterns": patterns,
                "keywords": keywords,
                "file_issues": file_issues,
                "sections": sections,
                "limit": limit,
                "commit": commit,
            }.items()
            if v is not None and v != []
        }

        try:
            if query_text and ids:
                return self._json(ErrorResponse(error="pass either query_text or ids, not both"))

            if _is_empty_call(
                query_text=query_text,
                ids=ids,
                kind=kind,
                type=type,
                entity_type=entity_type,
                file_extension=file_extension,
                path_prefix=path_prefix,
                quality=quality,
                complexity=complexity,
                security=security,
                testing=testing,
                testability=testability,
                documentation=documentation,
                performance=performance,
                issues=issues,
                maintainability=maintainability,
                architecture=architecture,
                technical_debt=technical_debt,
                cohesion=cohesion,
                coupling=coupling,
                stability=stability,
                priority=priority,
                needs_refactoring=needs_refactoring,
                vulnerabilities=vulnerabilities,
                frameworks=frameworks,
                domain=domain,
                concerns=concerns,
                layers=layers,
                patterns=patterns,
                keywords=keywords,
                file_issues=file_issues,
            ):
                return self._json(
                    ErrorResponse(
                        error=(
                            "codeindex_query was called without any narrowing input — "
                            "no query_text, no ids, no filters set. The call would return "
                            "arbitrary items.\n\n"
                            "If you meant to triage by severity / quality, pass a typed filter with "
                            "actual values, not `None`. Examples:\n"
                            "  codeindex_query(security=['major-issues','critical'])\n"
                            "  codeindex_query(vulnerabilities=['hardcoded-secret','sql-injection'])\n"
                            "  codeindex_query(needs_refactoring=True, priority=['high','critical'])\n\n"
                            "Note: passing `security=None` (or any other typed-filter arg as None) "
                            "is the SAME as not passing it — None means 'no filter on this dimension'. "
                            "Pass a list of severity values instead."
                        )
                    )
                )

            categorical_filters = _CategoricalFilters(
                kind=kind,
                type=type,
                entity_type=entity_type,
                file_extension=file_extension,
                path_prefix=path_prefix,
                quality=quality,
                complexity=complexity,
                security=security,
                testing=testing,
                testability=testability,
                documentation=documentation,
                performance=performance,
                issues=issues,
                maintainability=maintainability,
                architecture=architecture,
                technical_debt=technical_debt,
                cohesion=cohesion,
                coupling=coupling,
                stability=stability,
                priority=priority,
                needs_refactoring=needs_refactoring,
            )
            list_filters = _ListFilters(
                vulnerabilities=vulnerabilities or [],
                frameworks=frameworks or [],
                domain=domain or [],
                concerns=concerns or [],
                layers=layers or [],
                patterns=patterns or [],
                keywords=keywords or [],
                file_issues=file_issues or [],
            )

            response = await self._query_items(
                query_text=query_text,
                where=_build_where(categorical_filters),
                list_filters=list_filters,
                ids=ids,
                sections=tuple(sections) if sections else _DEFAULT_SECTIONS,
                limit=limit,
                commit=commit,
            )
            self._telemetry_log(
                {
                    "ts": _time.time(),
                    "tool": "codeindex_query",
                    "duration_ms": round((_time.monotonic() - _t0) * 1000, 1),
                    "args": _telemetry_args,
                    "response": response,
                    "response_chars": len(response),
                }
            )
            return response
        except Exception as exc:
            logger.exception("codeindex_query failed")
            return self._json(ErrorResponse(error=f"codeindex_query failed: {exc}"))

    # ── Internal: items ───────────────────────────────────────────────

    async def _query_items(
        self,
        *,
        query_text: str | None,
        where: dict[str, Any] | None,
        list_filters: _ListFilters,
        ids: list[str] | None,
        sections: tuple[Section, ...],
        limit: int,
        commit: str | None,
    ) -> str:
        idx = self._ensure_index()
        sha = commit or idx.head()
        if not sha:
            return self._json(ErrorResponse(error="no head commit; index may be empty"))
        if not idx.has_commit(sha):
            return self._json(ErrorResponse(error=f"no chroma index for commit {sha}"))

        # When a list filter is in play, fetch a wider candidate set
        # since post-filter may drop some — same idea as how semantic
        # search over-fetches before deduping by parent doc.
        fetch_limit = limit * 4 if list_filters.has_any else limit

        if query_text:
            rows = await idx.search(
                query=query_text, limit=fetch_limit, commit=sha, where=where or None
            )
        else:
            rows = await idx.filter_items(
                where=where or None, ids=ids, limit=fetch_limit, commit=sha
            )

        if list_filters.has_any:
            rows = [r for r in rows if list_filters.matches(r)]
        rows = rows[:limit]

        for r in rows:
            r.content = _filter_sections(r.content, sections)

        return ItemsResponse(
            commit=sha,
            items=rows,
            total=len(rows),
            truncated=len(rows) >= limit,
        ).model_dump_json(indent=2, exclude_none=True)

    # ── The other tool ────────────────────────────────────────────────

    async def codeindex_tree(
        self,
        id: str,
        sections: list[Section] | None = None,
        relations: list[Relation] | None = None,
        commit: str | None = None,
    ) -> str:
        """Drill into one item — fetch it plus every reference edge.

        Use this *after* ``codeindex_query`` has surfaced an item id
        you want to explore. The response is one ``CodeIndexResult``
        with ``references`` populated as
        ``{relation: [ReferenceTarget, …]}``: every immediate caller,
        callee, importer, etc. with id/name/path/summary, ready for
        the next ``codeindex_query(ids=[…])`` follow-up.

        Args:
            id: the uuid of the item (file / entity / folder) to expand.
            sections: which content sections to keep on the item itself
                (``Section`` enum groups). Default ``[summary]``.
            relations: only return edges with these relation kinds
                (``calls``, ``called_by``, ``imports``, ``imported_by``,
                etc.). Default: all kinds.
            commit: commit SHA. Defaults to current head.

        Returns: JSON ``ItemsResponse`` shape with a single item; the
            item's ``references`` map carries the full edge graph.
        """
        import time as _time

        _t0 = _time.monotonic()
        _telemetry_args = {
            k: v
            for k, v in {
                "id": id,
                "sections": sections,
                "relations": relations,
                "commit": commit,
            }.items()
            if v is not None and v != []
        }

        try:
            idx = self._ensure_index()
            sha = commit or idx.head()
            if not sha:
                return self._json(ErrorResponse(error="no head commit; index may be empty"))
            if not idx.has_commit(sha):
                return self._json(ErrorResponse(error=f"no chroma index for commit {sha}"))

            rows = await idx.filter_items(ids=[id], limit=1, commit=sha)
            if not rows:
                return self._json(ErrorResponse(error=f"no item with id {id!r}"))

            item = rows[0]
            section_tuple = tuple(sections) if sections else _DEFAULT_SECTIONS
            item.content = _filter_sections(item.content, section_tuple)

            await self._attach_references_to_item(idx, item, relations=relations)

            response = ItemsResponse(
                commit=sha,
                items=[item],
                total=1,
                truncated=False,
            ).model_dump_json(indent=2, exclude_none=True)
            self._telemetry_log(
                {
                    "ts": _time.time(),
                    "tool": "codeindex_tree",
                    "duration_ms": round((_time.monotonic() - _t0) * 1000, 1),
                    "args": _telemetry_args,
                    "response": response,
                    "response_chars": len(response),
                }
            )
            return response
        except Exception as exc:
            logger.exception("codeindex_tree failed")
            return self._json(ErrorResponse(error=f"codeindex_tree failed: {exc}"))

    # ── Reference-graph attachment (codeindex_tree only) ────────────

    async def _attach_references_to_item(
        self,
        idx: CodeIndex,
        item: CodeIndexResult,
        *,
        relations: list[Relation] | None,
    ) -> None:
        """Fetch every edge involving ``item.item_id`` from sqlite and
        attach them as ``item.references = {relation: [ReferenceTarget]}``.

        Each target's one-line summary is hydrated in a single batched
        chroma fetch. Items with no edges leave ``item.references`` at
        ``None`` so ``exclude_none=True`` strips the field.
        """
        if not item.item_id:
            return
        from ember_code.core.code_index.schema.items import ReferenceTarget

        relations_str = [str(r) for r in relations] if relations else None
        try:
            edges = await idx._file_reference_service().get_by_uuids(
                uuids=[item.item_id], relations=relations_str
            )
        except Exception:
            logger.exception("failed to attach references")
            return

        # Walk each edge once. The indexer stores the symmetric pair so
        # the relation name already encodes direction; we just need to
        # know which side of the edge ``item`` is on to pick the target
        # metadata fields.
        per_relation: dict[str, list[ReferenceTarget]] = {}
        for e in edges:
            if e.from_uuid == item.item_id:
                target = ReferenceTarget(
                    id=e.to_uuid,
                    name=str(e.meta.get("to_entity_name", "")),
                    path=str(e.meta.get("to_entity_path", "")),
                )
            elif e.to_uuid == item.item_id:
                target = ReferenceTarget(
                    id=e.from_uuid,
                    name=str(e.meta.get("from_entity_name", "")),
                    path=str(e.meta.get("from_entity_path", "")),
                )
            else:
                continue
            per_relation.setdefault(e.relation, []).append(target)

        if not per_relation:
            return
        item.references = per_relation

        await self._hydrate_target_summaries(idx, item)

    async def _hydrate_target_summaries(self, idx: CodeIndex, item: CodeIndexResult) -> None:
        """Batch-fetch each reference target's SUMMARY-section line and
        attach it to ``ReferenceTarget.summary``. One chroma call for
        every target across every relation. Targets whose source items
        aren't in chroma (or have no summary) keep the ``""`` default.
        """
        if not item.references:
            return
        unique_ids = {
            t.id for targets in item.references.values() for t in targets if t.id and not t.summary
        }
        if not unique_ids:
            return

        try:
            sha = idx.head()
            if not sha:
                return
            target_items = await idx.filter_items(
                ids=list(unique_ids), limit=len(unique_ids), commit=sha
            )
        except Exception:
            logger.exception("failed to fetch target items for reference summaries")
            return

        id_to_summary = {
            it.item_id: short for it in target_items if (short := _shorten_summary(it.content))
        }

        for targets in item.references.values():
            for t in targets:
                s = id_to_summary.get(t.id)
                if s:
                    t.summary = s


# ── empty-call guardrail ─────────────────────────────────────────────


def _is_empty_call(**kwargs: Any) -> bool:
    """True iff ``codeindex_query`` was invoked with no narrowing input.

    The agent's case-11-shape failure looks like
    ``codeindex_query(security=None, sections=[…], limit=15)`` — it reached
    for the right tool, named the dimension it wanted to triage on, but
    passed ``None`` instead of an actual list of severities. The call
    returns arbitrary ranked items; the agent reads them as "the worst
    offenders" and confabulates a triage. This helper detects that shape
    so the call site can return a didactic error instead.

    A call is "empty" when ALL of:
      - no ``query_text``
      - no ``ids``
      - every typed-filter arg is ``None`` (or an empty list, for the
        list-shaped multi-value categories).

    ``sections``, ``limit``, ``commit`` are output-control args that
    don't narrow — they don't count toward narrowing input.
    """
    if kwargs.get("query_text"):
        return False
    if kwargs.get("ids"):
        return False
    for name, value in kwargs.items():
        if name in ("query_text", "ids"):
            continue
        if value is None:
            continue
        if isinstance(value, list) and not value:
            continue
        # bool ``needs_refactoring`` is meaningful even when False — but
        # ``False`` filters to "items that don't need refactoring," which
        # is a real (if unusual) query, so accept it.
        return False
    return True


# ── where-clause builder ─────────────────────────────────────────────


def _enum_value(v: Any) -> Any:
    """StrEnum → raw string so chroma sees what it stored."""
    if hasattr(v, "value"):
        return v.value
    return v


def _build_where(filters: _CategoricalFilters) -> dict[str, Any] | None:
    """Translate :class:`_CategoricalFilters` into a chroma ``where`` filter.

    Every non-None field becomes one clause; multiple clauses combine
    under a top-level ``$and``. Single values become direct equality,
    lists become ``$in``.

    List-shaped multi-value categories live on :class:`_ListFilters`
    and are applied Python-side — chroma metadata ``where`` lacks a
    ``$contains`` operator, so they can't be pushed down here.

    Returns ``None`` when no filters were supplied so the index code
    skips the where-clause entirely (chroma rejects ``where={}``).
    """
    clauses: list[dict[str, Any]] = []

    # Direct exact-match scope filters.
    if filters.kind is not None:
        clauses.append({"kind": _enum_value(filters.kind)})
    if filters.type is not None:
        clauses.append({"type": filters.type})
    if filters.file_extension is not None:
        clauses.append({"file_extension": filters.file_extension})
    # ``path_prefix`` is reserved — chroma metadata where has no
    # $contains/prefix operator, so we accept the arg and ignore it
    # rather than silently emit a broken filter. Re-enable once
    # there's a where-document-based path matcher.

    # ``entity_type`` — single value or list.
    if filters.entity_type is not None:
        if isinstance(filters.entity_type, list):
            clauses.append({"entity_type": {"$in": [str(x) for x in filters.entity_type]}})
        else:
            clauses.append({"entity_type": str(filters.entity_type)})

    # ``needs_refactoring`` is bool.
    if filters.needs_refactoring is not None:
        clauses.append({"needs_refactoring": bool(filters.needs_refactoring)})

    # Quality categoricals.
    for field in _CATEGORICAL_QUALITY_FIELDS:
        v = getattr(filters, field)
        if v is None:
            continue
        if isinstance(v, list):
            values = [_enum_value(x) for x in v if x is not None]
            if not values:
                continue
            if len(values) == 1:
                clauses.append({field: values[0]})
            else:
                clauses.append({field: {"$in": values}})
        else:
            clauses.append({field: _enum_value(v)})

    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}
