"""Permission system — tool call approval with persistent allowlists."""

import fnmatch
from pathlib import Path
from typing import Literal

import yaml
from rich.console import Console
from rich.prompt import Prompt

from ember_code.core.config.settings import Settings

console = Console()

ApprovalChoice = Literal["once", "always", "similar", "deny"]


class PermissionGuard:
    """Guards tool calls with permission checks and approval prompts.

    Approval options:
    - once: approve this specific invocation only
    - always: permanently allow this exact command
    - similar: permanently allow a pattern (e.g., "npm *")
    - deny: block this invocation
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.permissions_path = Path.home() / ".ember" / "permissions.yaml"
        self.allowlist = self._load_allowlist()
        # Session-level one-time approvals
        self._session_approvals: set[str] = set()

    def _load_allowlist(self) -> dict[str, list[str]]:
        """Load persistent allowlist from ~/.ember/permissions.yaml."""
        if self.permissions_path.exists():
            with open(self.permissions_path) as f:
                data = yaml.safe_load(f)
                if isinstance(data, dict):
                    return data.get("allowlist", {})
        return {}

    def _save_allowlist(self):
        """Save allowlist to ~/.ember/permissions.yaml."""
        self.permissions_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.permissions_path, "w") as f:
            yaml.dump({"allowlist": self.allowlist}, f, default_flow_style=False)

    def _get_permission_level(self, category: str) -> str:
        """Get the permission level for a category."""
        perms = self.settings.permissions
        return getattr(perms, category, "ask")

    def _is_in_allowlist(self, category: str, value: str) -> bool:
        """Check if a value matches any entry in the allowlist."""
        entries = self.allowlist.get(category, [])
        return any(fnmatch.fnmatch(value, entry) for entry in entries)

    def _is_protected_path(self, path: str) -> bool:
        """Check if a path matches protected path patterns."""
        for pattern in self.settings.safety.protected_paths:
            if fnmatch.fnmatch(Path(path).name, pattern):
                return True
            if fnmatch.fnmatch(path, pattern):
                return True
        return False

    def _is_blocked_command(self, command: str) -> bool:
        """Check if a command matches blocked patterns."""
        return any(blocked in command for blocked in self.settings.safety.blocked_commands)

    def check_file_read(self, path: str) -> bool:
        """Check permission for file read."""
        level = self._get_permission_level("file_read")
        if level == "allow":
            return True
        if level == "deny":
            return False
        return self._prompt_approval("file_read", f"Read file: {path}", path)

    def check_file_write(self, path: str) -> bool:
        """Check permission for file write."""
        if self._is_protected_path(path):
            console.print(f"[red]Blocked:[/red] {path} is a protected path.")
            return False

        level = self._get_permission_level("file_write")
        if level == "allow":
            return True
        if level == "deny":
            return False
        if self._is_in_allowlist("file_write", path):
            return True
        return self._prompt_approval("file_write", f"Write file: {path}", path)

    def check_shell_execute(self, command: str) -> bool:
        """Check permission for shell command execution."""
        if self._is_blocked_command(command):
            console.print("[red]Blocked:[/red] Command matches blocked pattern.")
            return False

        # Check if it needs confirmation
        for pattern in self.settings.safety.require_confirmation:
            if command.startswith(pattern):
                return self._prompt_approval("shell_execute", f"Run: {command}", command)

        level = self._get_permission_level("shell_execute")
        if level == "allow":
            return True
        if level == "deny":
            return False
        if self._is_in_allowlist("shell_execute", command):
            return True
        return self._prompt_approval("shell_execute", f"Run: {command}", command)

    def _prompt_approval(self, category: str, description: str, value: str) -> bool:
        """Show approval prompt and handle the response."""
        # Check session approvals
        key = f"{category}:{value}"
        if key in self._session_approvals:
            return True

        console.print(f"\n[yellow]⚡ Permission required:[/yellow] {description}")
        console.print("  [y] Yes, allow once")
        console.print("  [a] Always allow")
        console.print("  [s] Allow similar")
        console.print("  [n] No, deny")

        choice = Prompt.ask("  Choice", choices=["y", "a", "s", "n"], default="n")

        if choice == "y":
            self._session_approvals.add(key)
            return True
        elif choice == "a":
            self.allowlist.setdefault(category, []).append(value)
            self._save_allowlist()
            return True
        elif choice == "s":
            # Generate a pattern from the value
            pattern = self._generate_pattern(value)
            self.allowlist.setdefault(category, []).append(pattern)
            self._save_allowlist()
            console.print(f"  [dim]Added pattern: {pattern}[/dim]")
            return True
        else:
            return False

    @staticmethod
    def _generate_pattern(value: str) -> str:
        """Generate a glob pattern from a value.

        Examples:
            "npm test" → "npm *"
            "pytest tests/" → "pytest *"
            "src/auth.py" → "src/*"
        """
        parts = value.split()
        if len(parts) > 1:
            return f"{parts[0]} *"
        # For file paths, use directory pattern
        path = Path(value)
        if path.parent != Path("."):
            return f"{path.parent}/*"
        return value
