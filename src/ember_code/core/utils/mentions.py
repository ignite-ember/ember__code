"""@file mention processing — shared between FE and BE runners."""

from __future__ import annotations

import re

_AT_MENTION_RE = re.compile(r"(?:^|(?<=\s))@(\S+)")


def process_file_mentions(text: str) -> tuple[str, list[str]]:
    """Strip @file mentions from message text and return referenced paths.

    Returns (cleaned_text, referenced_paths).  The ``@`` tokens are
    removed from the body entirely, and the referenced paths are
    surfaced via an ``<attached-files>`` hint block. The web FE
    strips that wrapper from the displayed user bubble (and from
    restored history), so what the user sees stays clean: just the
    prompt they typed.
    """
    paths: list[str] = []

    def _collect(m: re.Match) -> str:
        paths.append(m.group(1))
        # Preserve the literal @<path> token so the rendered bubble
        # (live AND restored) shows the user's reference inline.
        # The wrapper below tells the agent to actually read the
        # files — both representations stay in the message.
        return m.group(0)

    cleaned = _AT_MENTION_RE.sub(_collect, text)

    if paths:
        hint = (
            "<attached-files>\n"
            "[Referenced files: " + ", ".join(paths) + " — read before responding]\n"
            "</attached-files>"
        )
        cleaned = hint + ("\n" + cleaned if cleaned else "")

    return cleaned, paths
