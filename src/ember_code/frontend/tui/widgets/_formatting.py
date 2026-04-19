"""Shared formatting helpers for TUI widgets."""


def format_elapsed_time(seconds: float) -> str:
    """Format seconds: '0.8s', '3.2s', '1m 12s'."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}m {secs}s"


def format_token_count(n: int) -> str:
    """Format token count: 1234 -> '1.2k', 12345 -> '12k', 1000000 -> '1.0m'."""
    if n < 1000:
        return str(n)
    if n < 10_000:
        return f"{n / 1000:.1f}k"
    if n < 1_000_000:
        return f"{n // 1000}k"
    if n < 10_000_000:
        return f"{n / 1_000_000:.1f}m"
    if n < 1_000_000_000:
        return f"{n // 1_000_000}m"
    if n < 10_000_000_000:
        return f"{n / 1_000_000_000:.1f}b"
    if n < 1_000_000_000_000:
        return f"{n // 1_000_000_000}b"
    if n < 10_000_000_000_000:
        return f"{n / 1_000_000_000_000:.1f}t"
    return f"{n // 1_000_000_000_000}t"
