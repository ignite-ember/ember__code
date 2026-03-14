"""Single-message session runner."""

import time

from ember_code.config.settings import Settings
from ember_code.hooks.events import HookEvent
from ember_code.session.core import Session
from ember_code.utils.display import print_response, print_run_stats


async def run_single_message(
    settings: Settings,
    message: str,
    resume_session_id: str | None = None,
):
    """Run a single non-interactive message."""

    session = Session(
        settings,
        resume_session_id=resume_session_id,
    )

    await session.hook_executor.execute(
        event=HookEvent.SESSION_START.value,
        payload={"session_id": session.session_id},
    )

    start_time = time.monotonic()
    response = await session.handle_message(message)
    elapsed = time.monotonic() - start_time
    print_response(response)
    print_run_stats(
        elapsed_seconds=elapsed,
        model=session.settings.models.default,
    )

    await session.hook_executor.execute(
        event=HookEvent.SESSION_END.value,
        payload={"session_id": session.session_id},
    )
