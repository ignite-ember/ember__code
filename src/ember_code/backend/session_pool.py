"""SessionPool — route protocol messages to per-session BE runtimes.

One BE process, N live sessions, each owned by its own
``BackendServer`` (its own Agno team, run lock, HITL state). Views
bind to a session by stamping ``session_id`` on their messages; the
pool routes to the matching runtime, lazily resuming sessions that
aren't loaded yet. Runs on different sessions execute in parallel —
nothing is shared between runtimes except the process.

Id aliasing: ``/clear`` renews a runtime's internal session id, but
attached views keep stamping the id they bound to until they learn
the new one. Every id a runtime has EVER carried stays in
``known_ids`` so those in-flight messages still route to the same
runtime instead of spawning a ghost resume of the old id.

The default runtime (the one created at boot) handles messages with
an empty ``session_id`` — which is every message from the TUI, so
pre-pool views work unchanged.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SessionRuntime:
    """One live session: its BackendServer + per-runtime wiring."""

    backend: Any
    rpc_table: dict[str, Any]
    queue: list[str]
    transport: Any  # session-stamping transport wrapper
    known_ids: set[str] = field(default_factory=set)
    # Monotonic timestamp of the most recent ``find`` hit. Used by the
    # idle-eviction sweep so sessions a user hasn't touched in a while
    # can release their in-memory state (Agno team, chroma client,
    # cached embeddings). State on disk is unchanged — the next message
    # for an evicted session re-spawns a runtime via the resume path.
    # ``0.0`` means "never accessed" — older than every initialised
    # runtime, so an evictor sweeping at boot would NOT touch any
    # never-used runtime by mistake (we set this at creation).
    last_used_at: float = field(default=0.0)

    def remember_id(self) -> None:
        """Record the runtime's CURRENT session id as an alias.

        Called around every dispatch so id renames (``/clear``) keep
        routing stale-stamped messages to this runtime.
        """
        try:
            sid = self.backend.session_id
            if sid:
                self.known_ids.add(sid)
        except Exception:  # pragma: no cover — defensive
            pass


# Default: 30 minutes. Long enough that a user briefly switching to
# another project doesn't lose warm state when they come back; short
# enough that a forgotten BE doesn't hold every session it has ever
# seen forever. Tunable via ``SessionPool(idle_timeout_seconds=...)``.
_DEFAULT_IDLE_TIMEOUT = 30 * 60


class SessionPool:
    """Find-or-create SessionRuntimes keyed by (current or past) id."""

    def __init__(
        self,
        default: SessionRuntime,
        factory: Callable[[str], Awaitable[SessionRuntime]],
        *,
        idle_timeout_seconds: float = _DEFAULT_IDLE_TIMEOUT,
        clock: Callable[[], float] | None = None,
    ) -> None:
        import time

        # ``clock`` is injectable so tests can fast-forward without
        # sleeping the wall clock. Default to ``time.monotonic`` — its
        # tick is independent of the event loop's, which matters when
        # the loop is paused for a debugger.
        self._clock = clock if clock is not None else time.monotonic
        default.remember_id()
        # Stamp default's last_used_at so the eviction sweep doesn't
        # treat the boot runtime as "never used" → infinitely idle.
        default.last_used_at = self._clock()
        self._runtimes: list[SessionRuntime] = [default]
        self._factory = factory
        self._idle_timeout = idle_timeout_seconds
        # Serialises creation so two messages for the same not-yet-
        # loaded session don't resume it twice. Also held during
        # ``evict_idle`` so we never evict a runtime mid-resume.
        self._create_lock = asyncio.Lock()

    @property
    def default(self) -> SessionRuntime:
        return self._runtimes[0]

    @property
    def runtimes(self) -> list[SessionRuntime]:
        return list(self._runtimes)

    def find(self, session_id: str) -> SessionRuntime | None:
        if not session_id:
            self.default.last_used_at = self._clock()
            return self.default
        for rt in self._runtimes:
            rt.remember_id()
            if session_id in rt.known_ids:
                rt.last_used_at = self._clock()
                return rt
        return None

    async def get_or_create(self, session_id: str) -> SessionRuntime:
        rt = self.find(session_id)
        if rt is not None:
            return rt
        async with self._create_lock:
            # Re-check: another message may have created it while we
            # waited on the lock.
            rt = self.find(session_id)
            if rt is not None:
                return rt
            logger.info("session pool: resuming session %s", session_id)
            rt = await self._factory(session_id)
            rt.known_ids.add(session_id)
            rt.remember_id()
            rt.last_used_at = self._clock()
            self._runtimes.append(rt)
            return rt

    async def evict_idle(self) -> list[str]:
        """Drop runtimes idle longer than ``idle_timeout_seconds``.

        The default runtime (index 0) is NEVER evicted — it serves
        empty-``session_id`` traffic (the TUI's default behaviour)
        and there's no way to lazily resume "the default session"
        if it disappears.

        A runtime that's currently processing a run (``backend.processing``
        True) is also skipped — evicting mid-stream would cancel the
        active run and confuse the FE.

        Returns the list of evicted session ids for logging. Note:
        Python's allocator typically does not return freed pages to
        the OS, so process-RSS won't shrink immediately — but the
        memory IS reclaimed and reused by subsequent allocations,
        so a BE that cycles through many sessions reaches a steady
        working-set size instead of growing unboundedly.
        """
        async with self._create_lock:
            now = self._clock()
            cutoff = now - self._idle_timeout
            keep: list[SessionRuntime] = [self._runtimes[0]]
            evicted: list[str] = []
            for rt in self._runtimes[1:]:
                if rt.last_used_at >= cutoff:
                    keep.append(rt)
                    continue
                if getattr(rt.backend, "processing", False):
                    # Mid-run — leave alone; the next sweep picks it
                    # up once the run finishes and idle time grows.
                    keep.append(rt)
                    continue
                sid = ""
                with contextlib.suppress(Exception):  # pragma: no cover — defensive
                    sid = rt.backend.session_id or ""
                try:
                    await rt.backend.shutdown()
                except Exception as exc:  # pragma: no cover — defensive
                    logger.debug("evict shutdown failed for %s: %s", sid, exc)
                evicted.append(sid or "<unknown>")
                logger.info(
                    "session pool: evicted idle session %s (idle %.0fs)",
                    sid or "<unknown>",
                    now - rt.last_used_at,
                )
            self._runtimes = keep
            return evicted

    async def shutdown(self) -> None:
        for rt in self._runtimes:
            try:
                await rt.backend.shutdown()
            except Exception as exc:  # pragma: no cover — defensive
                logger.debug("runtime shutdown failed: %s", exc)


class SessionStampingTransport:
    """Transport wrapper that stamps outbound events with the
    emitting runtime's CURRENT session id (unless already stamped),
    so views can filter the broadcast stream to their bound session."""

    def __init__(self, inner: Any, backend: Any) -> None:
        self._inner = inner
        self._backend = backend

    async def send(self, message: Any) -> None:
        if not message.session_id:
            try:
                sid = self._backend.session_id
            except Exception:  # pragma: no cover — defensive
                sid = ""
            if sid:
                message = message.model_copy(update={"session_id": sid})
        await self._inner.send(message)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)
