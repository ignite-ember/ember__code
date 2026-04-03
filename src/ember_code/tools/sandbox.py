"""Sandboxed shell tools — restricts commands to the project directory."""

import logging
import re
from pathlib import Path

from agno.tools.shell import ShellTools

logger = logging.getLogger(__name__)

# Network commands blocked by default in sandbox mode
NETWORK_COMMANDS = frozenset(
    {
        "curl",
        "wget",
        "nc",
        "ncat",
        "netcat",
        "ssh",
        "scp",
        "sftp",
        "rsync",
        "ftp",
        "telnet",
        "nmap",
    }
)

# Patterns that indicate directory escape attempts
_ESCAPE_PATTERNS = [
    re.compile(r"\.\./"),  # ../
    re.compile(r"\.\.$"),  # .. at end
    re.compile(r";\s*cd\s+/"),  # ; cd /absolute
    re.compile(r"&&\s*cd\s+/"),  # && cd /absolute
    re.compile(r"\|\|\s*cd\s+/"),  # || cd /absolute
]


class SandboxViolation(Exception):
    """Raised when a shell command violates sandbox restrictions."""


def check_sandbox_command(
    command_str: str,
    project_dir: Path,
    allowed_network_commands: frozenset[str] | None = None,
) -> str | None:
    """Validate a shell command against sandbox restrictions.

    Returns None if the command is allowed, or an error message string
    if the command violates the sandbox.

    Args:
        command_str: The full command string to validate.
        project_dir: The project root directory.
        allowed_network_commands: Network commands explicitly permitted.

    Returns:
        None if allowed, or an error message describing the violation.
    """
    allowed_net = allowed_network_commands or frozenset()
    resolved_project = project_dir.resolve()

    # Tokenise to find the base commands in pipes/chains
    tokens = _extract_command_tokens(command_str)

    # 1. Block network commands (unless explicitly allowed)
    for token in tokens:
        base_cmd = Path(token).name  # handle /usr/bin/curl -> curl
        if base_cmd in NETWORK_COMMANDS and base_cmd not in allowed_net:
            return (
                f"Sandbox violation: network command '{base_cmd}' is not allowed. "
                f"Allowed network commands: {sorted(allowed_net) if allowed_net else 'none'}"
            )

    # 2. Block directory escape patterns
    for pattern in _ESCAPE_PATTERNS:
        if pattern.search(command_str):
            return (
                f"Sandbox violation: command contains directory escape pattern "
                f"(matched {pattern.pattern!r})"
            )

    # 3. Block cd to absolute paths outside project
    cd_targets = re.findall(r"cd\s+([^\s;&|]+)", command_str)
    for target in cd_targets:
        if target.startswith("/") or target.startswith("~"):
            # Resolve ~ to home
            resolved = Path(target).expanduser().resolve()
            if not _is_within(resolved, resolved_project):
                return (
                    f"Sandbox violation: 'cd {target}' escapes the project directory "
                    f"({resolved_project})"
                )

    # 4. Block absolute path arguments that reference outside project
    # Look for absolute paths in the command
    abs_paths = re.findall(r"(?:^|\s)(/[^\s;&|]+)", command_str)
    for abs_path in abs_paths:
        # Skip common system paths used as commands (e.g., /usr/bin/env)
        resolved = Path(abs_path).resolve()
        # Only block if it looks like a file argument (not the command itself)
        # Allow paths to executables in /usr, /bin, etc.
        if abs_path == tokens[0] if tokens else False:
            continue
        if _is_system_executable(abs_path):
            continue
        if not _is_within(resolved, resolved_project):
            return (
                f"Sandbox violation: absolute path '{abs_path}' is outside "
                f"the project directory ({resolved_project})"
            )

    return None


def _is_within(path: Path, parent: Path) -> bool:
    """Check if path is within parent directory."""
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _is_system_executable(path: str) -> bool:
    """Check if a path looks like a system executable (binary directory)."""
    system_dirs = ("/usr/bin/", "/usr/local/bin/", "/bin/", "/sbin/", "/usr/sbin/", "/opt/")
    return any(path.startswith(d) for d in system_dirs)


def _extract_command_tokens(command_str: str) -> list[str]:
    """Extract the base command names from a command string.

    Handles pipes, semicolons, &&, and ||.
    """
    # Split on shell operators
    parts = re.split(r"[|;&]+", command_str)
    tokens = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # Handle subshells, env vars, etc.
        # Skip leading env assignments (FOO=bar cmd)
        words = part.split()
        for word in words:
            if "=" in word and not word.startswith("-"):
                continue
            tokens.append(word)
            break
    return tokens


class SandboxedShellTools(ShellTools):
    """ShellTools wrapper that enforces sandbox restrictions.

    When sandbox mode is enabled, commands are:
    - Restricted to run in the project directory (working_dir)
    - Blocked from escaping via cd .., absolute paths outside project
    - Blocked from using network commands (curl, wget, etc.) unless allowed
    """

    def __init__(
        self,
        project_dir: Path | str,
        allowed_network_commands: list[str] | None = None,
        **kwargs,
    ):
        self._project_dir = Path(project_dir).resolve()
        self._allowed_network = frozenset(allowed_network_commands or [])
        # Always set base_dir to project_dir for sandboxed execution
        super().__init__(base_dir=self._project_dir, **kwargs)

    def run_shell_command(self, args: list[str], tail: int = 100) -> str:
        """Run a shell command with sandbox validation.

        Args:
            args: The command to run as a list of strings.
            tail: The number of lines to return from the output.

        Returns:
            str: The output of the command, or an error message.
        """
        command_str = " ".join(args)
        violation = check_sandbox_command(
            command_str,
            self._project_dir,
            self._allowed_network,
        )
        if violation:
            logger.warning("Sandbox blocked command: %s — %s", command_str, violation)
            return f"Error: {violation}"

        return super().run_shell_command(args, tail=tail)
