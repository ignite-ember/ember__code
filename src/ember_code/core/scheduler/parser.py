"""Natural language time parser for scheduling.

Uses ``dateparser`` for multilingual support (200+ languages).

Supports formats like:
- "in 5 minutes", "через 5 хвилин", "en 30 minutos"
- "at 5pm", "о 17:00", "a las 5pm"
- "tomorrow", "завтра", "mañana"
- "tomorrow at 9am", "завтра о 9 ранку"
- "2026-03-20 14:00"

Recurrence patterns (English):
- "every 30 minutes", "every 2 hours", "every 1 day"
- "daily", "hourly", "weekly"
- "daily at 9am", "weekly at 5pm"
"""

import re
from datetime import datetime, timedelta

import dateparser


def parse_time(text: str) -> datetime | None:
    """Parse a natural language time expression into a datetime.

    Uses dateparser for multilingual support. Falls back to None
    if the text can't be parsed.
    """
    text = text.strip()

    result = dateparser.parse(
        text,
        settings={
            "PREFER_DATES_FROM": "future",
            "RETURN_AS_TIMEZONE_AWARE": False,
        },
    )

    if result is None:
        return None

    # If the parsed time is in the past, push to tomorrow (for "at 5pm" style)
    is_explicit_date = re.search(r"\d{4}[-/]", text) or "tomorrow" in text.lower()
    if result <= datetime.now() and not is_explicit_date:
        result += timedelta(days=1)

    return result


# ── Recurrence ──────────────────────────────────────────────────


_RECURRENCE_ALIASES = {
    "hourly": "every 1 hours",
    "daily": "every 1 days",
    "weekly": "every 7 days",
}


def parse_recurrence(text: str) -> tuple[str, datetime | None]:
    """Parse a recurrence pattern and compute the first scheduled time.

    Args:
        text: e.g. "every 30 minutes", "daily", "daily at 9am", "hourly"

    Returns:
        (canonical_recurrence, first_scheduled_at) or ("", None) if not a recurrence.
    """
    text = text.strip().lower()

    # "daily at 9am" → split into recurrence + time
    at_time: datetime | None = None
    for alias, canonical in _RECURRENCE_ALIASES.items():
        if text.startswith(alias):
            rest = text[len(alias) :].strip()
            if rest.startswith("at"):
                at_time = parse_time(rest)
            elif not rest:
                at_time = _next_occurrence(canonical)
            if at_time is not None:
                return canonical, at_time

    # "every N units"
    m = re.match(r"every\s+(\d+)\s+(min(?:ute)?s?|hours?|days?|weeks?)", text)
    if m:
        amount = int(m.group(1))
        unit = m.group(2)
        canonical = f"every {amount} {_normalize_unit(unit)}"

        # Check for "every 2 hours at 9am"
        rest = text[m.end() :].strip()
        at_time = parse_time(rest) if rest.startswith("at") else _next_occurrence(canonical)

        if at_time is not None:
            return canonical, at_time

    return "", None


def next_occurrence_from_recurrence(recurrence: str, last_run: datetime) -> datetime | None:
    """Compute the next occurrence given a recurrence pattern and the last run time."""
    delta = _recurrence_to_delta(recurrence)
    if delta is None:
        return None
    return last_run + delta


def _next_occurrence(recurrence: str) -> datetime | None:
    """Compute the first occurrence from now."""
    delta = _recurrence_to_delta(recurrence)
    if delta is None:
        return None
    return datetime.now() + delta


def _recurrence_to_delta(recurrence: str) -> timedelta | None:
    """Convert canonical recurrence to timedelta."""
    m = re.match(r"every\s+(\d+)\s+(minutes?|hours?|days?|weeks?)", recurrence)
    if not m:
        return None
    amount = int(m.group(1))
    unit = m.group(2)
    if unit.startswith("minute"):
        return timedelta(minutes=amount)
    if unit.startswith("hour"):
        return timedelta(hours=amount)
    if unit.startswith("day"):
        return timedelta(days=amount)
    if unit.startswith("week"):
        return timedelta(weeks=amount)
    return None


def _normalize_unit(unit: str) -> str:
    """Normalize time unit to plural form."""
    if unit.startswith("min"):
        return "minutes"
    if unit.startswith("hour"):
        return "hours"
    if unit.startswith("day"):
        return "days"
    if unit.startswith("week"):
        return "weeks"
    return unit
