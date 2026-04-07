"""Single-message session runner."""

import time
from pathlib import Path

from ember_code.config.settings import Settings
from ember_code.hooks.events import HookEvent
from ember_code.session.core import Session
from ember_code.utils.display import print_response, print_run_stats


async def run_single_message(
    settings: Settings,
    message: str,
    resume_session_id: str | None = None,
    project_dir: Path | None = None,
    additional_dirs: list[Path] | None = None,
):
    """Run a single non-interactive message."""

    session = Session(
        settings,
        project_dir=project_dir,
        resume_session_id=resume_session_id,
        additional_dirs=additional_dirs,
    )

    await session.hook_executor.execute(
        event=HookEvent.SESSION_START.value,
        payload={"session_id": session.session_id},
    )

    # Auto-detect media (images, audio, videos, documents) from message text
    from ember_code.utils.media import parse_media_from_text

    cleaned_msg, media = parse_media_from_text(message)
    media_kwargs = media.as_kwargs()
    if media.has_media:
        message = cleaned_msg
        from ember_code.utils.display import print_info

        print_info(f"Attached: {media.summary()}")

    start_time = time.monotonic()
    response = await session.handle_message(message, **media_kwargs)
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
