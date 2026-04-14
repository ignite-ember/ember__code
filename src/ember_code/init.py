"""Project initializer and updater for .ember directory.

Two responsibilities:
1. **First-run init** — copies built-in agents, skills, hooks into `.ember/`
   and creates a starter `ember.md`.  Marker file ensures this runs once.
2. **Update on every start** — compares package files against local copies
   using checksums.  Overwrites untouched files, warns about modified ones.
"""

import hashlib
import json
import logging
import shutil
import stat
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────

PACKAGE_ROOT = Path(__file__).parent.parent.parent  # repo root
MARKER_FILE = ".initialized"
CHECKSUMS_FILE = ".checksums.json"


# ── Built-in hook scripts ─────────────────────────────────────────────

SESSION_CONTEXT_HOOK = """\
#!/bin/bash
# .ember/hooks/session-context.sh
# Hook: SessionStart
#
# Reports current branch, uncommitted changes, and stale TODO on session start.

branch=$(git branch --show-current 2>/dev/null || echo "unknown")
uncommitted=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
behind=$(git rev-list HEAD..@{u} --count 2>/dev/null || echo "0")

parts=()
[[ "$branch" != "unknown" ]] && parts+=("branch: $branch")
[[ "$uncommitted" -gt 0 ]] && parts+=("$uncommitted uncommitted change(s)")
[[ "$behind" -gt 0 ]] && parts+=("$behind commit(s) behind remote")

# Check for stale TODO.md
if [[ -f ".ember/TODO.md" ]]; then
  last_modified=$(stat -f %m .ember/TODO.md 2>/dev/null || stat -c %Y .ember/TODO.md 2>/dev/null || echo "0")
  now=$(date +%s)
  age_days=$(( (now - last_modified) / 86400 ))
  [[ "$age_days" -gt 7 ]] && parts+=("TODO.md is ${age_days} days old")
fi

# Check if ember.md exists
[[ ! -f "ember.md" ]] && parts+=("no ember.md found — consider creating one")

if [[ ${#parts[@]} -eq 0 ]]; then
  echo '{"continue": true}'
  exit 0
fi

msg=$(IFS=", "; echo "${parts[*]}")
cat << EOF
{"continue": true, "systemMessage": "Session context: ${msg}"}
EOF
exit 0
"""

TEST_REMINDER_HOOK = """\
#!/bin/bash
# .ember/hooks/test-reminder.sh
# Hook: Stop
#
# Before the agent finishes, checks if source files were modified but no
# tests were updated or run. If so, blocks and reminds to run tests.

changed_files=$(git diff --name-only HEAD 2>/dev/null; git diff --name-only --cached 2>/dev/null; git ls-files --others --exclude-standard 2>/dev/null)

if [[ -z "$changed_files" ]]; then
  echo '{"continue": true}'
  exit 0
fi

# Check if source files were modified
source_changed=false
while IFS= read -r file; do
  case "$file" in
    *.py|*.ts|*.tsx|*.js|*.jsx|*.go|*.rs|*.java|*.rb|*.c|*.cpp)
      # Skip test files
      case "$file" in
        test_*|*_test.*|*.test.*|*_spec.*|*.spec.*|tests/*|__tests__/*|spec/*) continue ;;
      esac
      source_changed=true
      break
      ;;
  esac
done <<< "$changed_files"

if [[ "$source_changed" != "true" ]]; then
  echo '{"continue": true}'
  exit 0
fi

# Check if test files were also modified
test_changed=false
while IFS= read -r file; do
  case "$file" in
    test_*|*_test.*|*.test.*|*_spec.*|*.spec.*|tests/*|__tests__/*|spec/*)
      test_changed=true
      break
      ;;
  esac
done <<< "$changed_files"

if [[ "$test_changed" == "true" ]]; then
  echo '{"continue": true}'
  exit 0
fi

cat << EOF
{
  "continue": false,
  "systemMessage": "Source files were modified but no tests were updated. Run tests to verify your changes, or confirm that no test updates are needed."
}
EOF
exit 2
"""

PRE_PR_REVIEW_HOOK = """\
#!/bin/bash
# .ember/hooks/pre-pr-review.sh
# Hook: PreToolUse (matcher: Bash)
#
# Early warning: catches TODOs, debug statements, and console.log before
# push or PR creation. This is NOT enforcement — real gates belong in CI/CD.

# Read payload from stdin
payload=$(cat)
cmd=$(echo "$payload" | grep -o '"command"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"command"[[:space:]]*:[[:space:]]*"//;s/"$//')

# Only check push/PR commands
case "$cmd" in
  *"git push"*|*"gh pr create"*|*"gh pr"*) ;;
  *) echo '{"continue": true}'; exit 0 ;;
esac

# Check for leftover debug/TODO in staged changes
diff_output=$(git diff --cached 2>/dev/null || git diff HEAD 2>/dev/null)
issues=()

todo_count=$(echo "$diff_output" | grep "^+" | grep -c -i "TODO\\|FIXME\\|HACK\\|XXX" || true)
todo_count=$(echo "$todo_count" | tr -d '[:space:]')
[[ "$todo_count" -gt 0 ]] 2>/dev/null && issues+=("$todo_count TODO/FIXME comment(s)")

debug_count=$(echo "$diff_output" | grep "^+" | grep -c "console\\.log\\|debugger\\|breakpoint()\\|import pdb\\|print(" || true)
debug_count=$(echo "$debug_count" | tr -d '[:space:]')
[[ "$debug_count" -gt 0 ]] 2>/dev/null && issues+=("$debug_count debug statement(s)")

if [[ ${#issues[@]} -eq 0 ]]; then
  echo '{"continue": true}'
  exit 0
fi

msg=$(IFS=", "; echo "${issues[*]}")
cat << EOF
{
  "continue": false,
  "systemMessage": "Before pushing: found ${msg} in your changes. Address these or confirm they are intentional."
}
EOF
exit 2
"""

POST_COMMIT_TODO_HOOK = """\
#!/bin/bash
# .ember/hooks/post-commit-todo.sh
# Hook: PostToolUse (matcher: Bash, background: true)
#
# After a git commit, scan committed files for new TODOs and append them
# to .ember/TODO.md if it exists.

payload=$(cat)
cmd=$(echo "$payload" | grep -o '"command"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"command"[[:space:]]*:[[:space:]]*"//;s/"$//')

# Only act on commit commands
case "$cmd" in
  *"git commit"*) ;;
  *) echo '{"continue": true}'; exit 0 ;;
esac

# Only if TODO.md exists
if [[ ! -f ".ember/TODO.md" ]]; then
  echo '{"continue": true}'
  exit 0
fi

# Find TODOs in last commit
new_todos=$(git diff HEAD~1..HEAD 2>/dev/null | grep "^+" | grep -i "TODO\\|FIXME" | sed 's/^+//' | head -10)

if [[ -z "$new_todos" ]]; then
  echo '{"continue": true}'
  exit 0
fi

# Append to TODO.md
echo "" >> .ember/TODO.md
echo "## New TODOs (auto-detected $(date +%Y-%m-%d))" >> .ember/TODO.md
while IFS= read -r line; do
  echo "- [ ] $line" >> .ember/TODO.md
done <<< "$new_todos"

echo '{"continue": true}'
exit 0
"""

BUILT_IN_HOOKS = [
    {
        "filename": "session-context.sh",
        "content": SESSION_CONTEXT_HOOK,
        "event": "SessionStart",
        "definition": {
            "type": "command",
            "command": ".ember/hooks/session-context.sh",
            "timeout": 10000,
        },
    },
    {
        "filename": "test-reminder.sh",
        "content": TEST_REMINDER_HOOK,
        "event": "Stop",
        "definition": {
            "type": "command",
            "command": ".ember/hooks/test-reminder.sh",
            "timeout": 10000,
        },
    },
    {
        "filename": "pre-pr-review.sh",
        "content": PRE_PR_REVIEW_HOOK,
        "event": "PreToolUse",
        "definition": {
            "type": "command",
            "command": ".ember/hooks/pre-pr-review.sh",
            "matcher": "Bash",
            "timeout": 15000,
        },
    },
    {
        "filename": "post-commit-todo.sh",
        "content": POST_COMMIT_TODO_HOOK,
        "event": "PostToolUse",
        "definition": {
            "type": "command",
            "command": ".ember/hooks/post-commit-todo.sh",
            "matcher": "Bash",
            "timeout": 15000,
            "background": True,
        },
    },
]

# ── Starter ember.md template ─────────────────────────────────────────

EMBER_MD_TEMPLATE = """\
# Project Context

<!-- This file gives Ember Code agents context about your project.
     Edit it to match your project's specifics. Agents read this file
     before every task to understand conventions, architecture, and
     domain terminology. -->

## Overview

<!-- Brief description of what this project does. -->

## Tech Stack

<!-- Languages, frameworks, key libraries. -->

## Architecture

<!-- High-level structure: key directories, module boundaries, data flow. -->

## Conventions

<!-- Naming, formatting, patterns the team follows. -->

## Domain Terminology

<!-- Project-specific terms and their meanings. -->
"""


CONFIG_YAML_HEADER = """\
# Ember Code — user configuration
# This file lives at ~/.ember/config.yaml and is never committed to git.
# Project-level overrides go in .ember/config.yaml inside your repo.
# See https://docs.ignite-ember.sh/configuration for details.

"""

PROJECT_CONFIG_TEMPLATE = """\
# Ember Code — project configuration
# This file can be committed to git. Team members share these settings.
# User-level overrides go in ~/.ember/config.yaml.
# See https://docs.ignite-ember.sh/configuration for details.

# models:
#   default: MiniMax-M2.7        # Default model for this project

guardrails:
  pii_detection: true             # Warn on PII in user messages
  # prompt_injection: false       # Warn on prompt injection patterns

knowledge:
  enabled: true                   # ChromaDB knowledge base
  collection_name: ember_knowledge

memory:
  enable_agentic_memory: true     # Remember facts across sessions (extracts every 10 messages)

# orchestration:
#   max_nesting_depth: 5          # Max recursive sub-team levels
#   max_total_agents: 20          # Max agents per request
#   sub_team_timeout: 600         # Sub-team kill timeout (seconds)
"""


# ── Public API ────────────────────────────────────────────────────────


def initialize_project(project_dir: Path) -> bool:
    """Initialize and update the project's .ember directory.

    First run: copies built-in agents, skills, hooks, creates ember.md.
    Subsequent runs: updates built-in files using checksum-based merge:
      - Untouched files → overwritten with new package version
      - User-modified files → kept, warning logged
      - New package files → copied
      - User's custom files → never deleted
    """
    home_ember = Path.home() / ".ember"
    home_ember.mkdir(parents=True, exist_ok=True)
    home_marker = home_ember / MARKER_FILE
    project_marker = project_dir / ".ember" / MARKER_FILE

    ember_dir = project_dir / ".ember"
    ember_dir.mkdir(parents=True, exist_ok=True)

    # Write home config if missing (user-global, first-ever run)
    if not home_marker.exists():
        _write_default_config(home_ember)
        home_marker.touch()

    # First-time project init: copy everything + create starter files
    first_run = not project_marker.exists()
    if first_run:
        _write_ember_md(project_dir)
        _write_project_config(project_dir)
        project_marker.touch()

    # Always run update — handles both first-run copy and subsequent updates
    warnings = _update_built_in_files(project_dir)
    _provision_hooks(project_dir)

    for msg in warnings:
        logger.info(msg)

    return first_run


# ── Checksum-based update ────────────────────────────────────────────


def _file_hash(path: Path) -> str:
    """Compute SHA-256 hash of a file's content."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _load_checksums(project_dir: Path) -> dict[str, str]:
    """Load .ember/.checksums.json — maps relative paths to original hashes."""
    path = project_dir / ".ember" / CHECKSUMS_FILE
    return _load_json(path)


def _save_checksums(project_dir: Path, checksums: dict[str, str]) -> None:
    """Save .ember/.checksums.json."""
    path = project_dir / ".ember" / CHECKSUMS_FILE
    _save_json(path, checksums)


def _update_built_in_files(project_dir: Path) -> list[str]:
    """Sync built-in agents and skills using checksum-based merge.

    Returns a list of warning messages for files that were modified by the
    user and could not be auto-updated.
    """
    checksums = _load_checksums(project_dir)
    warnings: list[str] = []

    # Update agents
    agents_src = PACKAGE_ROOT / "agents"
    agents_dst = project_dir / ".ember" / "agents"
    if agents_src.exists():
        agents_dst.mkdir(parents=True, exist_ok=True)
        for src_file in agents_src.glob("*.md"):
            key = f"agents/{src_file.name}"
            dst_file = agents_dst / src_file.name
            warn = _sync_file(src_file, dst_file, key, checksums)
            if warn:
                warnings.append(warn)

    # Update skills
    skills_src = PACKAGE_ROOT / "skills"
    skills_dst = project_dir / ".ember" / "skills"
    if skills_src.exists():
        for skill_dir in skills_src.iterdir():
            if not skill_dir.is_dir():
                continue
            src_file = skill_dir / "SKILL.md"
            if not src_file.exists():
                continue
            key = f"skills/{skill_dir.name}/SKILL.md"
            dst_dir = skills_dst / skill_dir.name
            dst_dir.mkdir(parents=True, exist_ok=True)
            dst_file = dst_dir / "SKILL.md"
            warn = _sync_file(src_file, dst_file, key, checksums)
            if warn:
                warnings.append(warn)

    _save_checksums(project_dir, checksums)
    return warnings


def _sync_file(src: Path, dst: Path, key: str, checksums: dict[str, str]) -> str | None:
    """Sync a single built-in file. Returns a warning string or None.

    Logic:
      - dst doesn't exist → copy, record checksum
      - no stored checksum (legacy) → record current package hash, skip update
      - package unchanged → skip
      - package changed + user didn't modify → overwrite, update checksum
      - package changed + user modified → skip, return warning
    """
    pkg_hash = _file_hash(src)
    stored_hash = checksums.get(key)

    if not dst.exists():
        # New file — copy and record
        shutil.copy2(src, dst)
        checksums[key] = pkg_hash
        return None

    if stored_hash is None:
        # Legacy: file exists but no checksum recorded.
        # Record current package hash so future updates work.
        checksums[key] = pkg_hash
        return None

    if pkg_hash == stored_hash:
        # Package hasn't changed — nothing to do
        return None

    # Package has changed — check if user modified their copy
    local_hash = _file_hash(dst)

    if local_hash == stored_hash:
        # User hasn't touched it — safe to overwrite
        shutil.copy2(src, dst)
        checksums[key] = pkg_hash
        return None

    # User modified AND package updated — write new version alongside
    new_path = dst.with_suffix(dst.suffix + ".new")
    shutil.copy2(src, new_path)
    checksums[key] = pkg_hash
    return (
        f"Built-in {key} was updated but you have local modifications. "
        f"New version saved as .ember/{key}.new — diff and merge at your convenience."
    )


# ── Internal helpers ──────────────────────────────────────────────────


def _write_default_config(home_ember: Path) -> None:
    """Write a starter config.yaml from DEFAULT_CONFIG if one doesn't exist."""
    config_path = home_ember / "config.yaml"
    if not config_path.exists():
        import yaml

        from ember_code.config.defaults import DEFAULT_CONFIG

        config_path.write_text(
            CONFIG_YAML_HEADER
            + yaml.dump(
                DEFAULT_CONFIG,
                default_flow_style=False,
                sort_keys=False,
            )
        )


def _provision_hooks(project_dir: Path) -> None:
    """Write built-in hook scripts and register them in settings.

    Hook scripts are always overwritten (they are not user-customizable
    in the same way agents/skills are — users configure hooks via
    settings.json, not by editing the scripts).
    """
    hooks_dir = project_dir / ".ember" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    home_ember = Path.home() / ".ember"
    home_ember.mkdir(parents=True, exist_ok=True)
    settings_path = home_ember / "settings.json"
    settings = _load_json(settings_path)

    for hook in BUILT_IN_HOOKS:
        # Write the hook script (always overwrite — hooks are code, not config)
        script_path = hooks_dir / hook["filename"]
        script_path.write_text(hook["content"])
        script_path.chmod(script_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        # Register in settings (skip if already registered)
        event = hook["event"]
        definition = hook["definition"]
        event_hooks = settings.setdefault("hooks", {}).setdefault(event, [])
        if not any(h.get("command") == definition["command"] for h in event_hooks):
            event_hooks.append(definition)

    _save_json(settings_path, settings)


def _write_ember_md(project_dir: Path) -> None:
    """Write a starter ember.md if one doesn't exist."""
    path = project_dir / "ember.md"
    if not path.exists():
        path.write_text(EMBER_MD_TEMPLATE)


def _write_project_config(project_dir: Path) -> None:
    """Write a starter .ember/config.yaml with commented-out options."""
    path = project_dir / ".ember" / "config.yaml"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(PROJECT_CONFIG_TEMPLATE)


def _load_json(path: Path) -> dict:
    """Load a JSON file, returning empty dict if missing or invalid."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_json(path: Path, data: dict) -> None:
    """Write a dict as formatted JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
