"""Hooks system — pre/post tool execution hooks."""

from ember_code.core.hooks.events import HookEvent
from ember_code.core.hooks.executor import HookExecutor
from ember_code.core.hooks.loader import HookLoader
from ember_code.core.hooks.schemas import HookDefinition, HookResult

__all__ = [
    "HookLoader",
    "HookDefinition",
    "HookResult",
    "HookExecutor",
    "HookEvent",
]
