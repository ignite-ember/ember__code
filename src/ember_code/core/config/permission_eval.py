"""Claude Code-style 6-mode tool permission evaluator.

Pure module: parses ``Tool(pattern)`` rules, holds a
``PermissionMode``, and walks the 6-step evaluation pipeline
(``hooks → deny → ask → mode → allow → defer``). No I/O, no
network, no interactive prompts — those happen in the layer that
calls this evaluator (the tool-event hook, eventually a UI bridge).

Modelled on `code.claude.com/docs/en/agent-sdk/permissions`. The
TS-only ``auto`` mode (model classifier) is intentionally absent
from the Python surface.

The key safety invariant: a deny rule with a scope pattern (e.g.
``Bash(rm *)``) STILL blocks matching invocations in
``bypassPermissions`` mode. Only bare-name denies (e.g. plain
``Bash``) follow the "remove the tool from context" shortcut and
that lives at a different layer.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Any


class PermissionMode(StrEnum):
    """Top-level permission posture for a session.

    Defaults to ``DEFAULT``. ``DONT_ASK`` is the headless/CI mode
    (never prompt, deny unmatched). ``ACCEPT_EDITS`` auto-approves
    file mutation tools. ``BYPASS_PERMISSIONS`` runs without
    prompts unless an explicit deny / ask rule matches.
    ``PLAN`` forbids source edits entirely.
    """

    DEFAULT = "default"
    DONT_ASK = "dontAsk"
    ACCEPT_EDITS = "acceptEdits"
    BYPASS_PERMISSIONS = "bypassPermissions"
    PLAN = "plan"


class PermissionDecision(Enum):
    """Outcome of one evaluation step.

    ``DEFER`` is the "no rule applies, fall through to the next
    step / canUseTool callback" value — needed because returning
    ``None`` for "no decision" mixed too easily with the other
    truthy/falsy answers in callers.
    """

    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"
    DEFER = "defer"


# Tools that mutate the filesystem — used by ``acceptEdits``
# (auto-approve) and ``plan`` (block). Names match Claude Code's
# Edit/Write/NotebookEdit set, plus ember-code's ``edit_file_*`` /
# ``save_file`` / ``create_file`` variants. ``run_shell_command``
# is intentionally not in this set: a shell command may or may not
# mutate state, and the safer default is "treat as default-mode".
FILE_EDIT_TOOLS = frozenset(
    {
        "Edit",
        "Write",
        "NotebookEdit",
        "save_file",
        "edit_file",
        "edit_file_replace_all",
        "create_file",
    }
)


# Matches ``ToolName`` or ``ToolName(pattern)`` rule strings. The
# tool name is ``[A-Za-z_][A-Za-z0-9_]*``; the pattern (when
# present) is everything between the parens, kept verbatim so
# globs / paths / quoted strings survive intact.
_RULE_RE = re.compile(r"^(?P<tool>[A-Za-z_][A-Za-z0-9_]*)(?:\((?P<pattern>.*)\))?$")


@dataclass(frozen=True)
class PermissionRule:
    """A single ``Tool`` or ``Tool(pattern)`` rule.

    ``pattern is None`` means "bare-name rule" — matches any
    invocation of the tool regardless of arguments. A pattern
    matches the tool's most-distinctive string argument (``command``
    for shell, ``file_path``/``path`` for file tools) via
    ``fnmatch``.
    """

    tool: str
    pattern: str | None

    @classmethod
    def parse(cls, raw: str) -> PermissionRule | None:
        """Parse a string like ``"Bash"``, ``"Bash(npm test)"``,
        ``"Read(./.env)"``, or ``"*"`` (wildcard). Returns ``None``
        if the string can't be parsed — the caller should skip it
        with a warning rather than crash the whole pipeline."""
        raw = raw.strip()
        if not raw:
            return None
        if raw == "*":
            return cls(tool="*", pattern=None)
        m = _RULE_RE.match(raw)
        if not m:
            return None
        return cls(tool=m["tool"], pattern=m["pattern"])

    def matches(self, tool_name: str, tool_args: dict[str, Any]) -> bool:
        """Does this rule match an invocation of ``tool_name`` with
        ``tool_args``? Wildcard tool (``*``) matches anything. A
        rule with no pattern matches any invocation of the named
        tool. With a pattern, the tool's primary string argument is
        fnmatched against the pattern."""
        if self.tool != "*" and self.tool != tool_name:
            return False
        if self.pattern is None:
            return True
        target = _primary_arg(tool_name, tool_args)
        if target is None:
            return False
        return fnmatch.fnmatchcase(target, self.pattern)


def _primary_arg(tool_name: str, tool_args: dict[str, Any]) -> str | None:
    """Pick the argument we match the pattern against. Ordering
    matters: ``command`` first (shell tools), then ``file_path``,
    ``path``, ``filename`` — same priority the tool-event hook
    uses elsewhere for path harvesting."""
    for key in ("command", "file_path", "path", "filename", "url"):
        v = tool_args.get(key)
        if isinstance(v, str) and v:
            return v
    # ``args`` list (legacy shell tools): join with spaces so a
    # pattern like ``rm *`` matches ``["rm", "-rf", "build"]``.
    args_list = tool_args.get("args")
    if isinstance(args_list, list) and args_list:
        return " ".join(str(a) for a in args_list)
    return None


@dataclass
class PermissionEvaluator:
    """The 6-step evaluation pipeline.

    Order (matching Claude Code's contract):
      1. ``hooks`` — fired by the tool-event hook BEFORE this
         evaluator runs; not modelled here.
      2. ``deny`` — any matching deny rule → ``DENY``. Bypass-
         resistant: still wins in ``bypassPermissions`` mode.
      3. ``ask`` — any matching ask rule → ``ASK`` (caller asks
         the user / canUseTool).
      4. ``mode`` — mode-specific shortcut: ``acceptEdits``
         auto-allows file-edit tools, ``plan`` denies them,
         ``bypassPermissions`` allows everything not already
         denied/asked, ``dontAsk`` denies anything not allowed.
      5. ``allow`` — any matching allow rule → ``ALLOW``.
      6. ``defer`` — return ``DEFER`` so the caller routes to its
         interactive/UI/canUseTool fallback.
    """

    mode: PermissionMode = PermissionMode.DEFAULT
    deny: list[PermissionRule] = field(default_factory=list)
    ask: list[PermissionRule] = field(default_factory=list)
    allow: list[PermissionRule] = field(default_factory=list)

    @classmethod
    def from_strings(
        cls,
        mode: str | PermissionMode = PermissionMode.DEFAULT,
        deny: list[str] | None = None,
        ask: list[str] | None = None,
        allow: list[str] | None = None,
    ) -> PermissionEvaluator:
        """Convenience constructor — accepts raw strings from
        ``settings.permissions`` and parses them into
        ``PermissionRule`` objects, silently dropping malformed
        entries (caller can check the lengths if it cares)."""
        return cls(
            mode=PermissionMode(mode) if isinstance(mode, str) else mode,
            deny=_parse_rules(deny or []),
            ask=_parse_rules(ask or []),
            allow=_parse_rules(allow or []),
        )

    def evaluate(self, tool_name: str, tool_args: dict[str, Any]) -> PermissionDecision:
        # Step 2: deny
        if _any_match(self.deny, tool_name, tool_args):
            return PermissionDecision.DENY

        # Step 3: ask
        if _any_match(self.ask, tool_name, tool_args):
            return PermissionDecision.ASK

        # Step 4: mode-specific shortcuts
        mode_decision = self._mode_step(tool_name)
        if mode_decision is not PermissionDecision.DEFER:
            return mode_decision

        # Step 5: allow
        if _any_match(self.allow, tool_name, tool_args):
            return PermissionDecision.ALLOW

        # Step 6: defer (caller's canUseTool / interactive prompt)
        if self.mode is PermissionMode.DONT_ASK:
            # Headless mode: no prompts means anything unmatched
            # at this point is a deny, not a defer.
            return PermissionDecision.DENY
        return PermissionDecision.DEFER

    def _mode_step(self, tool_name: str) -> PermissionDecision:
        is_edit_tool = tool_name in FILE_EDIT_TOOLS
        if self.mode is PermissionMode.PLAN and is_edit_tool:
            return PermissionDecision.DENY
        if self.mode is PermissionMode.ACCEPT_EDITS and is_edit_tool:
            return PermissionDecision.ALLOW
        if self.mode is PermissionMode.BYPASS_PERMISSIONS:
            # Anything not already denied or asked is auto-allowed.
            return PermissionDecision.ALLOW
        return PermissionDecision.DEFER


def _parse_rules(raws: list[str]) -> list[PermissionRule]:
    parsed: list[PermissionRule] = []
    for raw in raws:
        rule = PermissionRule.parse(raw)
        if rule is not None:
            parsed.append(rule)
    return parsed


def _any_match(rules: list[PermissionRule], tool_name: str, tool_args: dict[str, Any]) -> bool:
    return any(r.matches(tool_name, tool_args) for r in rules)
