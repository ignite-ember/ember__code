"""BackendProcess — spawns and manages the BE subprocess."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
import uuid
from pathlib import Path

from ember_code.frontend.tui.backend_client import BackendClient

logger = logging.getLogger(__name__)


class BackendProcess:
    """Spawns BackendServer as a subprocess and connects via Unix socket."""

    def __init__(
        self,
        project_dir: Path | None = None,
        resume_session_id: str | None = None,
        additional_dirs: list[Path] | None = None,
        settings: object | None = None,
        debug: bool = False,
    ):
        self._project_dir = project_dir or Path.cwd()
        self._resume_session_id = resume_session_id
        self._additional_dirs = additional_dirs
        self._settings = settings
        self._debug = debug
        self._socket_path = f"/tmp/ember-code/{uuid.uuid4().hex[:12]}.sock"
        self._process: asyncio.subprocess.Process | None = None
        self._client: BackendClient | None = None

    async def start(self) -> BackendClient:
        """Spawn BE subprocess, wait for READY, return connected client."""
        # Ensure socket directory exists
        Path(self._socket_path).parent.mkdir(parents=True, exist_ok=True)

        # Build command
        cmd = [
            sys.executable,
            "-m",
            "ember_code.backend",
            "--socket",
            self._socket_path,
            "--project-dir",
            str(self._project_dir),
        ]
        if self._resume_session_id:
            cmd.extend(["--resume-session", self._resume_session_id])
        if self._additional_dirs:
            for d in self._additional_dirs:
                cmd.extend(["--additional-dirs", str(d)])
        if self._debug:
            cmd.append("--debug")

        logger.info("Spawning BE: %s", " ".join(cmd))

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Wait for JSON ready signal on stdout (skip non-JSON lines like warnings)
        import json

        try:
            deadline = asyncio.get_event_loop().time() + 60.0
            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    raise asyncio.TimeoutError
                line = await asyncio.wait_for(self._process.stdout.readline(), timeout=remaining)
                text = line.decode().strip()
                if not text:
                    continue
                try:
                    data = json.loads(text)
                    if data.get("status") == "ready":
                        logger.info("BE ready: %s", text)
                        break
                except json.JSONDecodeError:
                    # Skip non-JSON lines (library warnings, model load reports)
                    logger.debug("BE stdout (non-JSON): %s", text[:200])
                    continue
        except asyncio.TimeoutError:
            self._process.kill()
            stderr = await self._process.stderr.read()
            raise RuntimeError(
                f"BE failed to start within 60s. stderr: {stderr.decode()[:500]}"
            ) from None

        # Connect client
        self._client = BackendClient(self._socket_path)
        await self._client.connect()

        # Cache initial state
        if self._settings:
            self._client._cached_settings = self._settings
        await self._client.refresh_cache()

        return self._client

    async def stop(self) -> None:
        """Send shutdown and wait for process to exit."""
        if self._client:
            with contextlib.suppress(Exception):
                await self._client.shutdown()

        if self._process:
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("BE did not exit gracefully, killing")
                self._process.kill()

        # Cleanup socket file
        socket_path = Path(self._socket_path)
        if socket_path.exists():
            socket_path.unlink()

    def is_alive(self) -> bool:
        """Check if the BE process is running."""
        return self._process is not None and self._process.returncode is None

    @property
    def client(self) -> BackendClient | None:
        return self._client
