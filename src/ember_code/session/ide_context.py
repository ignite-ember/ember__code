"""IDE context tracker — tracks open files and active editor from IDE events.

Builds a picture of the user's IDE state by:
1. Parsing system-reminder messages for file-open events
2. Querying MCP IDE tools (getDiagnostics) when available
3. Maintaining an ordered list of recently opened files

Agents can use this context to understand what the user is looking at
and prioritize their work accordingly.
"""

import re
import time

from pydantic import BaseModel, Field


class OpenFile(BaseModel):
    """A file the user has open in their IDE."""

    path: str
    opened_at: float = Field(default_factory=time.time)
    is_active: bool = False
    diagnostics: list[dict] = Field(default_factory=list)


class IDEContext:
    """Tracks IDE state throughout a session.

    Maintains a list of files the user has opened and which one is
    currently active. Updated by parsing system-reminder messages
    and MCP getDiagnostics responses.
    """

    # Pattern matching "The user opened the file /path/to/file.ext in the IDE"
    FILE_OPEN_PATTERN = re.compile(r"The user opened the file\s+(\S+)\s+in the IDE")

    def __init__(self, max_files: int = 50):
        self._files: dict[str, OpenFile] = {}
        self._active_file: str | None = None
        self._max_files = max_files

    @property
    def active_file(self) -> str | None:
        """The file currently focused in the IDE."""
        return self._active_file

    @property
    def open_files(self) -> list[OpenFile]:
        """All tracked open files, most recently opened first."""
        return sorted(
            self._files.values(),
            key=lambda f: f.opened_at,
            reverse=True,
        )

    @property
    def open_file_paths(self) -> list[str]:
        """Paths of all tracked open files, most recent first."""
        return [f.path for f in self.open_files]

    def track_file(self, path: str, active: bool = True) -> None:
        """Record that a file was opened or focused."""
        # Deactivate previous active file
        if active and self._active_file and self._active_file in self._files:
            self._files[self._active_file].is_active = False

        if path in self._files:
            self._files[path].opened_at = time.time()
            self._files[path].is_active = active
        else:
            self._files[path] = OpenFile(path=path, is_active=active)

        if active:
            self._active_file = path

        self._evict_old()

    def parse_system_reminder(self, text: str) -> str | None:
        """Extract and track file-open events from system-reminder text.

        Returns the file path if a file-open event was found, None otherwise.
        """
        match = self.FILE_OPEN_PATTERN.search(text)
        if match:
            path = match.group(1)
            self.track_file(path)
            return path
        return None

    def parse_message(self, message: str) -> None:
        """Scan a message for any embedded system-reminder file events."""
        # System reminders may be embedded in <system-reminder> tags
        for match in re.finditer(
            r"<system-reminder>(.*?)</system-reminder>",
            message,
            re.DOTALL,
        ):
            self.parse_system_reminder(match.group(1))

    def update_from_diagnostics(self, diagnostics_response: list[dict]) -> None:
        """Update context from an MCP getDiagnostics response.

        The response is a list of {uri: str, diagnostics: list[dict]}.
        The first entry is typically the active file.
        """
        for i, entry in enumerate(diagnostics_response):
            uri = entry.get("uri", "")
            # Convert file:///path to /path
            path = uri[7:] if uri.startswith("file://") else uri

            if not path:
                continue

            diags = entry.get("diagnostics", [])
            is_active = i == 0  # First entry is the active file
            self.track_file(path, active=is_active)
            self._files[path].diagnostics = diags

    def describe(self) -> str:
        """Generate a human-readable summary for injection into agent context."""
        if not self._files:
            return ""

        lines = ["## IDE Context"]

        if self._active_file:
            lines.append(f"**Active file:** `{self._active_file}`")

        other_files = [f.path for f in self.open_files if f.path != self._active_file]
        if other_files:
            lines.append(f"**Other open files:** {', '.join(f'`{p}`' for p in other_files[:10])}")

        # Show diagnostics for active file if any
        if self._active_file and self._active_file in self._files:
            diags = self._files[self._active_file].diagnostics
            if diags:
                lines.append(f"**Diagnostics ({len(diags)}):**")
                for d in diags[:5]:
                    severity = d.get("severity", "")
                    msg = d.get("message", "")
                    rng = d.get("range", {})
                    start = rng.get("start", {})
                    line = start.get("line", "?")
                    lines.append(f"  - L{line}: [{severity}] {msg}")

        return "\n".join(lines)

    def _evict_old(self) -> None:
        """Remove oldest files if we exceed max tracked files."""
        if len(self._files) <= self._max_files:
            return

        sorted_files = sorted(
            self._files.items(),
            key=lambda kv: kv[1].opened_at,
        )
        to_remove = len(self._files) - self._max_files
        for key, _ in sorted_files[:to_remove]:
            if key != self._active_file:
                del self._files[key]
