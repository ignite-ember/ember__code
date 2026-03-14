"""Hook loader — discovers and loads hooks from settings files."""

import json
import sys
from pathlib import Path

from ember_code.hooks.schemas import HookDefinition


class HookLoader:
    """Loads hook definitions from settings files."""

    def __init__(self, project_dir: Path | None = None):
        self.project_dir = project_dir or Path.cwd()

    def load(self) -> dict[str, list[HookDefinition]]:
        """Load hooks from all settings files.

        Settings locations (merged, later wins):
        1. ~/.ember/settings.json (global)
        2. .ember/settings.json (project)
        3. .ember/settings.local.json (project, gitignored)
        """
        hooks: dict[str, list[HookDefinition]] = {}

        paths = [
            Path.home() / ".ember" / "settings.json",
            self.project_dir / ".ember" / "settings.json",
            self.project_dir / ".ember" / "settings.local.json",
        ]

        for path in paths:
            self._load_from_file(path, hooks)

        return hooks

    def _load_from_file(self, path: Path, hooks: dict[str, list[HookDefinition]]) -> None:
        """Load hooks from a single settings file."""
        if not path.exists():
            return

        try:
            with open(path) as f:
                data = json.load(f)

            hooks_data = data.get("hooks", {})
            for event_name, hook_list in hooks_data.items():
                if not isinstance(hook_list, list):
                    continue
                for hook_data in hook_list:
                    hook = HookDefinition(
                        type=hook_data.get("type", "command"),
                        command=hook_data.get("command", ""),
                        url=hook_data.get("url", ""),
                        headers=hook_data.get("headers", {}),
                        matcher=hook_data.get("matcher", ""),
                        timeout=hook_data.get("timeout", 10000),
                    )
                    hooks.setdefault(event_name, []).append(hook)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: Failed to load hooks from {path}: {e}", file=sys.stderr)


# Backward compatibility
def load_hooks(project_dir: Path | None = None) -> dict[str, list[HookDefinition]]:
    """Convenience wrapper around HookLoader.load()."""
    return HookLoader(project_dir).load()
