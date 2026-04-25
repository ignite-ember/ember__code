"""Non-blocking shell tool with process management.

Replaces Agno's ShellTools with an async-aware implementation that:
- Runs commands with a configurable timeout (default 120s)
- Supports background/long-running processes (servers, watchers)
- Lets the AI read output incrementally and stop processes
- Kills subprocesses on cancellation instead of hanging forever
"""

import logging
import os
import signal
import subprocess
import threading
import time
from pathlib import Path

from agno.tools import Toolkit

logger = logging.getLogger(__name__)

# Maximum output buffer size per process (1MB)
_MAX_BUFFER = 1_048_576
# Maximum characters in a tool result returned to the AI
_MAX_RESULT_CHARS = 30_000


def _truncate(text: str, limit: int = _MAX_RESULT_CHARS) -> str:
    """Truncate output to avoid sending huge tool results to the LLM."""
    if len(text) <= limit:
        return text
    half = limit // 2
    return (
        text[:half] + f"\n\n... ({len(text) - limit} characters truncated) ...\n\n" + text[-half:]
    )


class _ManagedProcess:
    """Tracks a running subprocess and its output."""

    __slots__ = ("proc", "output", "lock", "started_at", "cmd", "finished", "_read_cursor")

    def __init__(self, proc: subprocess.Popen, cmd: str):
        self.proc = proc
        self.cmd = cmd
        self.output: list[str] = []
        self.lock = threading.Lock()
        self.started_at = time.monotonic()
        self.finished = False
        self._read_cursor: int = 0  # tracks position for read_new()

    def _reader(self) -> None:
        """Background thread that drains stdout+stderr."""
        assert self.proc.stdout is not None
        try:
            for raw_line in self.proc.stdout:
                line = raw_line.rstrip("\n")
                with self.lock:
                    self.output.append(line)
                    # Trim if buffer is too large (keep last half)
                    total = sum(len(line) for line in self.output)
                    if total > _MAX_BUFFER:
                        self.output = self.output[len(self.output) // 2 :]
        except ValueError:
            pass  # stream closed
        finally:
            self.finished = True

    def read(self, tail: int = 100) -> str:
        """Return the last `tail` lines of output."""
        with self.lock:
            lines = self.output[-tail:]
        return "\n".join(lines)

    def read_new(self, max_lines: int = 200) -> str:
        """Return only lines added since the last read_new() call."""
        with self.lock:
            new = self.output[self._read_cursor : self._read_cursor + max_lines]
            self._read_cursor = min(self._read_cursor + max_lines, len(self.output))
        return "\n".join(new)

    def is_running(self) -> bool:
        return self.proc.poll() is None

    def returncode(self) -> int | None:
        return self.proc.poll()

    def kill(self) -> None:
        """Kill the process tree."""
        import contextlib

        with contextlib.suppress(ProcessLookupError, OSError):
            os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
        with contextlib.suppress(ProcessLookupError, OSError):
            self.proc.kill()


class _ProcessRegistry:
    """Global registry of managed background processes."""

    def __init__(self) -> None:
        self._processes: dict[int, _ManagedProcess] = {}
        self._lock = threading.Lock()

    def add(self, mp: _ManagedProcess) -> int:
        pid = mp.proc.pid
        with self._lock:
            self._processes[pid] = mp
        return pid

    def get(self, pid: int) -> _ManagedProcess | None:
        with self._lock:
            return self._processes.get(pid)

    def remove(self, pid: int) -> None:
        with self._lock:
            self._processes.pop(pid, None)

    def all_running(self) -> list[tuple[int, str, float]]:
        """Return (pid, cmd, elapsed_seconds) for running processes."""
        with self._lock:
            result = []
            for pid, mp in self._processes.items():
                if mp.is_running():
                    elapsed = time.monotonic() - mp.started_at
                    result.append((pid, mp.cmd, elapsed))
            return result

    def kill_all(self) -> int:
        """Kill all tracked processes. Returns count killed."""
        with self._lock:
            count = 0
            for mp in self._processes.values():
                if mp.is_running():
                    mp.kill()
                    count += 1
            self._processes.clear()
            return count


# Singleton registry shared across all tool instances
_registry = _ProcessRegistry()

# Tracks the currently running foreground process so it can be killed on cancel.
_foreground_lock = threading.Lock()
_foreground_process: _ManagedProcess | None = None


def cancel_foreground() -> bool:
    """Kill the active foreground process. Called on Escape/cancel.

    Returns True if a process was killed.
    """
    global _foreground_process
    with _foreground_lock:
        mp = _foreground_process
        if mp is not None and mp.is_running():
            mp.kill()
            _foreground_process = None
            return True
    return False


class EmberShellTools(Toolkit):
    """Non-blocking shell tool with process management.

    Provides three tools:
    - run_shell_command: Execute a command (blocks up to timeout, then backgrounds it)
    - read_process_output: Read output from a backgrounded process
    - stop_process: Stop a running process
    """

    def __init__(self, base_dir: str | None = None, **kwargs):
        # Extract requires_confirmation_tools before super().__init__
        # because Agno validates it before register() is called.
        confirm_tools = kwargs.pop("requires_confirmation_tools", None)
        super().__init__(name="ember_shell", **kwargs)
        self.base_dir = Path(base_dir) if base_dir else None
        self.register(self.run_shell_command)
        self.register(self.read_process_output)
        self.register(self.watch_process)
        self.register(self.stop_process)
        self.register(self.list_processes)
        if confirm_tools:
            self.requires_confirmation_tools = confirm_tools

    def run_shell_command(
        self,
        args: list[str],
        timeout: int = 7,
        background: bool = False,
        tail: int = 100,
    ) -> str:
        """Run a shell command and return its output.

        For short-lived commands (ls, git, grep, cat, curl), waits up to
        `timeout` seconds and returns the output.

        For long-running commands (servers, watchers, anything that runs
        indefinitely), you MUST set background=True. This starts the process
        and returns its PID with initial output. Use watch_process(pid) to
        monitor and stop_process(pid) to stop.

        Examples of commands that MUST use background=True:
        - uvicorn, gunicorn, flask run, npm start, python -m http.server
        - docker compose up, npm run dev, tail -f, watch
        - Any command that starts a server or runs indefinitely

        If a foreground command exceeds the timeout, it is automatically
        backgrounded and its PID is returned.

        Args:
            args: Command and arguments as a list, e.g. ["python", "-m", "uvicorn", "main:app"].
            timeout: Max seconds to wait for the command to finish. Default 7.
            background: If True, start in background and return PID immediately.
            tail: Number of output lines to return. Default 100.

        Returns:
            Command output, or a message with the PID for background processes.
        """
        cmd_str = " ".join(args)
        logger.info("Shell: running %s (timeout=%d, bg=%s)", cmd_str, timeout, background)

        try:
            proc = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=str(self.base_dir) if self.base_dir else None,
                start_new_session=True,  # new process group for clean kills
            )
        except Exception as e:
            return f"Error starting command: {e}"

        mp = _ManagedProcess(proc, cmd_str)

        # Start output reader thread
        reader = threading.Thread(target=mp._reader, daemon=True)
        reader.start()

        pid = _registry.add(mp)

        if background:
            # Auto-watch for a few seconds to capture startup output or crash
            time.sleep(3)
            output = mp.read_new()
            if not mp.is_running():
                rc = mp.returncode()
                _registry.remove(pid)
                return f"Background process exited immediately (code {rc}):\n{output}"
            status = f"Background process running (PID {pid}): {cmd_str}\n"
            if output:
                status += f"\nStartup output:\n{output}\n"
            else:
                status += "\nNo output yet (process is running silently).\n"
            status += f"\nUse watch_process({pid}) to monitor, stop_process({pid}) to stop."
            return status

        # Track as foreground so cancel_foreground() can kill it
        global _foreground_process
        with _foreground_lock:
            _foreground_process = mp

        # Poll instead of proc.wait() so the process can be killed mid-wait
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            time.sleep(0.25)

        with _foreground_lock:
            _foreground_process = None

        if proc.poll() is None:
            # Command is still running — treat it as backgrounded
            output = mp.read(tail=tail)
            return _truncate(
                f"Command still running after {timeout}s — backgrounded as PID {pid}.\n"
                f"Use read_process_output({pid}) to check output.\n"
                f"Use stop_process({pid}) to stop it.\n\n"
                f"Output so far:\n{output}"
            )

        # Command finished — collect remaining output
        reader.join(timeout=2)
        output = mp.read(tail=tail)
        rc = proc.returncode
        _registry.remove(pid)

        if rc != 0:
            return _truncate(f"Command exited with code {rc}:\n{output}")
        return _truncate(output)

    def read_process_output(self, pid: int, tail: int = 100) -> str:
        """Read recent output from a running or finished background process.

        Args:
            pid: Process ID returned by run_shell_command.
            tail: Number of lines to return. Default 100.

        Returns:
            Recent output lines and process status.
        """
        mp = _registry.get(pid)
        if mp is None:
            return f"No tracked process with PID {pid}."

        output = mp.read(tail=tail)
        if mp.is_running():
            elapsed = time.monotonic() - mp.started_at
            return _truncate(f"[Running for {elapsed:.0f}s — PID {pid}]\n{output}")
        else:
            rc = mp.returncode()
            _registry.remove(pid)
            return _truncate(f"[Finished — exit code {rc}]\n{output}")

    def watch_process(self, pid: int, seconds: int = 10) -> str:
        """Watch a background process for a period, then return new output.

        Collects output for `seconds` seconds (or until the process exits),
        then returns only the NEW lines produced during that window. Use this
        after starting a background process to verify it works, or to monitor
        a running server for errors. Call repeatedly to keep watching.

        Args:
            pid: Process ID to watch.
            seconds: How many seconds to watch (1–30). Default 10.

        Returns:
            New output produced during the watch window, plus process status.
        """
        mp = _registry.get(pid)
        if mp is None:
            return f"No tracked process with PID {pid}."

        seconds = max(1, min(seconds, 30))

        # Wait for output or process exit
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if not mp.is_running():
                break
            time.sleep(0.5)

        new_output = mp.read_new()
        elapsed = time.monotonic() - mp.started_at

        if mp.is_running():
            if new_output:
                return f"[Running for {elapsed:.0f}s — PID {pid}]\nNew output:\n{new_output}"
            return (
                f"[Running for {elapsed:.0f}s — PID {pid}]\nNo new output in the last {seconds}s."
            )
        else:
            rc = mp.returncode()
            _registry.remove(pid)
            if new_output:
                return f"[Exited with code {rc} after {elapsed:.0f}s]\nOutput:\n{new_output}"
            return f"[Exited with code {rc} after {elapsed:.0f}s]\nNo new output before exit."

    def stop_process(self, pid: int) -> str:
        """Stop a running background process.

        Args:
            pid: Process ID to stop.

        Returns:
            Confirmation message.
        """
        mp = _registry.get(pid)
        if mp is None:
            return f"No tracked process with PID {pid}."

        if not mp.is_running():
            rc = mp.returncode()
            output = mp.read(tail=20)
            _registry.remove(pid)
            return f"Process {pid} already finished (exit code {rc}).\nLast output:\n{output}"

        mp.kill()
        mp.proc.wait(timeout=5)
        output = mp.read(tail=20)
        _registry.remove(pid)
        return f"Process {pid} stopped.\nLast output:\n{output}"

    def list_processes(self) -> str:
        """List all running background processes.

        Returns:
            Table of running processes with PID, command, and elapsed time.
        """
        running = _registry.all_running()
        if not running:
            return "No background processes running."

        lines = ["PID    | Elapsed | Command", "-------+---------+--------"]
        for pid, cmd, elapsed in running:
            lines.append(f"{pid:<6} | {elapsed:>5.0f}s  | {cmd}")
        return "\n".join(lines)

    @staticmethod
    def cleanup() -> int:
        """Kill all tracked processes. Called on session shutdown."""
        return _registry.kill_all()
