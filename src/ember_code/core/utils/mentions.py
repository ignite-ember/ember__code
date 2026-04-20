"""@file mention processing — shared between FE and BE runners."""

from __future__ import annotations

import re

_AT_MENTION_RE = re.compile(r"(?:^|(?<=\s))@(\S+)")


def process_file_mentions(text: str) -> tuple[str, list[str]]:
    """Strip @file mentions from message text and return referenced paths.

    Returns (cleaned_text, referenced_paths).  The ``@`` prefix is removed
    so the agent sees a natural file path.  A hint line is prepended when
    files are referenced.
    """
    paths: list[str] = []

    def _replace(m: re.Match) -> str:
        path = m.group(1)
        paths.append(path)
        return path

    cleaned = _AT_MENTION_RE.sub(_replace, text)

    if paths:
        hint = "[Referenced files: " + ", ".join(paths) + " — read before responding]"
        cleaned = hint + "\n" + cleaned

    return cleaned, paths
