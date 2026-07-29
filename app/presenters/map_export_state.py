"""Immutable lifecycle state for Explorer map exports."""
from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class MapExportState:
    """Ownership snapshot for one map export request."""

    generation: int = 0
    is_running: bool = False
    cancel_requested: bool = False
    is_disposed: bool = False


def begin_map_export(state: MapExportState) -> MapExportState:
    """Start a new export generation unless the owner is unavailable."""
    if state.is_disposed or state.is_running:
        return state
    return MapExportState(
        generation=state.generation + 1,
        is_running=True,
    )


def request_map_export_cancel(state: MapExportState) -> MapExportState:
    """Mark the active export as cancellation-pending."""
    if not state.is_running or state.cancel_requested:
        return state
    return replace(state, cancel_requested=True)


def finish_map_export(
    state: MapExportState,
    generation: int,
) -> MapExportState:
    """Release a matching export while preserving callback identity."""
    if not owns_map_export(state, generation):
        return state
    return replace(
        state,
        is_running=False,
        cancel_requested=False,
    )


def dispose_map_export(state: MapExportState) -> MapExportState:
    """Invalidate pending callbacks and permanently close the owner."""
    if state.is_disposed:
        return state
    return MapExportState(
        generation=state.generation + 1,
        is_disposed=True,
    )


def invalidate_map_export(state: MapExportState) -> MapExportState:
    """Invalidate one world session while keeping the dialog reusable.

    Args:
        state: Current export ownership state.

    Returns:
        An idle generation that rejects callbacks from the old world.
    """
    if state.is_disposed:
        return state
    return MapExportState(generation=state.generation + 1)


def owns_map_export(state: MapExportState, generation: int) -> bool:
    """Return whether a callback belongs to the active export request."""
    return (
        not state.is_disposed
        and state.is_running
        and generation == state.generation
    )


__all__ = [
    "MapExportState",
    "begin_map_export",
    "dispose_map_export",
    "finish_map_export",
    "invalidate_map_export",
    "owns_map_export",
    "request_map_export_cancel",
]
