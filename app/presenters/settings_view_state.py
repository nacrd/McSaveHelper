"""设置页保存与重置反馈的不可变状态机。"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class SettingsFeedbackPhase(str, Enum):
    """设置持久化的用户可见阶段。"""

    AUTO = "auto"
    PENDING = "pending"
    SAVED = "saved"
    FAILED = "failed"
    RESETTING = "resetting"


@dataclass(frozen=True)
class SettingsViewState:
    """设置页异步反馈和生命周期状态。"""

    feedback: SettingsFeedbackPhase = SettingsFeedbackPhase.AUTO
    operation_busy: bool = False
    is_disposed: bool = False

    @property
    def can_start_operation(self) -> bool:
        """Return whether save/reset work may be started."""
        return not self.is_disposed and not self.operation_busy


def mark_save_pending(state: SettingsViewState) -> SettingsViewState:
    """Project a queued save when the page can accept work."""
    if not state.can_start_operation:
        return state
    return replace(state, feedback=SettingsFeedbackPhase.PENDING)


def mark_save_succeeded(state: SettingsViewState) -> SettingsViewState:
    """Project successful persistence unless the page was disposed."""
    if state.is_disposed:
        return state
    return replace(state, feedback=SettingsFeedbackPhase.SAVED)


def mark_save_failed(state: SettingsViewState) -> SettingsViewState:
    """Project failed persistence and release an exclusive operation."""
    if state.is_disposed:
        return state
    return replace(
        state,
        feedback=SettingsFeedbackPhase.FAILED,
        operation_busy=False,
    )


def begin_reset(state: SettingsViewState) -> SettingsViewState:
    """Enter the exclusive reset phase when no operation is active."""
    if not state.can_start_operation:
        return state
    return replace(
        state,
        feedback=SettingsFeedbackPhase.RESETTING,
        operation_busy=True,
    )


def complete_reset(state: SettingsViewState) -> SettingsViewState:
    """Complete reset and restore normal interaction."""
    if state.is_disposed:
        return state
    return replace(
        state,
        feedback=SettingsFeedbackPhase.SAVED,
        operation_busy=False,
    )


def dispose_settings_state(state: SettingsViewState) -> SettingsViewState:
    """Invalidate later UI callbacks and release local busy state."""
    return replace(state, operation_busy=False, is_disposed=True)


__all__ = [
    "SettingsFeedbackPhase",
    "SettingsViewState",
    "begin_reset",
    "complete_reset",
    "dispose_settings_state",
    "mark_save_failed",
    "mark_save_pending",
    "mark_save_succeeded",
]
