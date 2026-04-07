"""Shared utilities for DARKWATER services."""

from __future__ import annotations

from typing import Any

__all__ = ["ProcessingStatus", "ensure_file_state_table", "get_status", "upsert_status"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from . import state

        return getattr(state, name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
