"""Project initializer — one-time setup of .ember directory for new users.

Runs once per project on first session start. Copies built-in agents, skills,
and hooks into the user's `.ember/` directory and creates a starter `ember.md`.
A marker file (`.ember/.initialized`) ensures this never runs again — if the
user deletes anything, it stays deleted.
"""

import json
import shutil
import stat
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────

PACKAGE_ROOT = Path(__file__).parent.parent.parent  # repo root
MARKER_FILE = ".initialized"


# ── Built-in hook scripts ─────────────────────────────────────────────

DOCS_REMIND_HOOK = """\
#!/bin/bash
# .ember/hooks/docs-remind.sh
# Hook: Stop
#
# Before the agent finishes, checks if source files were modified but no
# documentation was updated. If so, blocks and reminds to run /update-docs.

# Get all modified files (staged + unstaged + untracked)
changed_files=$(git diff --name-only HEAD 2>/dev/null; git diff --name-only --cached 2>/dev/null; git ls-files --others --exclude-standard 2>/dev/null)

if [[ -z "$changed_files" ]]; then
  echo '{"continue": true}'
  exit 0
fi

# Check if any source files were modified
source_changed=false
source_count=0
while IFS= read -r file; do
  case "$file" in
    src/*.py|agents/*.md|skills/*/SKILL.md|pyproject.toml|Makefile)
      source_changed=true
      source_count=$((source_count + 1))
      ;;
  esac
done <<< "$changed_files"

if [[ "$source_changed" != "true" ]]; then
  echo '{"continue": true}'
  exit 0
fi

# Check if any docs were also modified
docs_changed=false
while IFS= read -r file; do
  case "$file" in
    README.md|QUICKSTART.md|TODO.md|CHANGELOG.md|PROGRESS.md|docs/*|docs/progress/*)
      docs_changed=true
      break
      ;;
  esac
done <<< "$changed_files"

if [[ "$docs_changed" == "true" ]]; then
  echo '{"continue": true}'
  exit 0
fi

# Source changed, no docs updated — remind
cat << EOF
{
  "continue": false,
  "systemMessage": "${source_count} source file(s) were modified but no documentation was updated. Run /update-docs to keep docs in sync, or confirm that no doc updates are needed for these changes."
}
EOF
exit 2
"""

BUILT_IN_HOOKS = [
    {
        "filename": "docs-remind.sh",
        "content": DOCS_REMIND_HOOK,
        "event": "Stop",
        "definition": {
            "type": "command",
            "command": ".ember/hooks/docs-remind.sh",
            "timeout": 10000,
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
    """Run one-time project initialization.

    Copies built-in agents, skills, and hooks into the project's `.ember/`
    directory and creates a starter `ember.md`. Settings and the marker
    file live in `~/.ember/` (user home, outside any repo).

    This function is idempotent — once `~/.ember/.initialized` exists,
    this is a no-op forever.
    """
    home_ember = Path.home() / ".ember"
    home_ember.mkdir(parents=True, exist_ok=True)
    home_marker = home_ember / MARKER_FILE
    project_marker = project_dir / ".ember" / MARKER_FILE

    # Skip if both home and project are already initialized
    if home_marker.exists() and project_marker.exists():
        return False

    ember_dir = project_dir / ".ember"
    ember_dir.mkdir(parents=True, exist_ok=True)

    # Always write home config if missing (user-global)
    if not home_marker.exists():
        _write_default_config(home_ember)
        home_marker.touch()

    # Initialize project if its marker is missing (e.g. .ember/ was deleted)
    if not project_marker.exists():
        _copy_agents(project_dir)
        _copy_skills(project_dir)
        _provision_hooks(project_dir)
        _write_ember_md(project_dir)
        _write_project_config(project_dir)
        project_marker.touch()

    return True


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


def _copy_agents(project_dir: Path) -> None:
    """Copy built-in agent definitions to .ember/agents/."""
    src = PACKAGE_ROOT / "agents"
    dst = project_dir / ".ember" / "agents"

    if not src.exists():
        return

    dst.mkdir(parents=True, exist_ok=True)

    for md_file in src.glob("*.md"):
        target = dst / md_file.name
        if not target.exists():
            shutil.copy2(md_file, target)


def _copy_skills(project_dir: Path) -> None:
    """Copy built-in skill definitions to .ember/skills/."""
    src = PACKAGE_ROOT / "skills"
    dst = project_dir / ".ember" / "skills"

    if not src.exists():
        return

    for skill_dir in src.iterdir():
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue

        target_dir = dst / skill_dir.name
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / "SKILL.md"
        if not target.exists():
            shutil.copy2(skill_file, target)


def _provision_hooks(project_dir: Path) -> None:
    """Write built-in hook scripts and register them in settings.

    Hook scripts go in the project's `.ember/hooks/` directory.
    Hook registrations go in `~/.ember/settings.json` (user global).
    """
    ember_dir = project_dir / ".ember"
    hooks_dir = ember_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    home_ember = Path.home() / ".ember"
    home_ember.mkdir(parents=True, exist_ok=True)
    settings_path = home_ember / "settings.json"
    settings = _load_json(settings_path)

    for hook in BUILT_IN_HOOKS:
        # Write the hook script
        script_path = hooks_dir / hook["filename"]
        script_path.write_text(hook["content"])
        script_path.chmod(script_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        # Register in settings
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
