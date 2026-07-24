"""存档对比页的不可变 ViewState 与状态转换。"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Sequence

from app.services.world_compare_service import CompareItem, WorldCompareResult


class ComparePhase(str, Enum):
    """对比页面可观察阶段。"""

    IDLE = "idle"
    RUNNING = "running"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass(frozen=True)
class CompareItemState:
    """一条差异的只读 UI 投影。"""

    name: str
    left: str
    right: str


@dataclass(frozen=True)
class CompareGroupState:
    """一个对比分组的只读 UI 投影。"""

    title: str
    items: tuple[CompareItemState, ...]


@dataclass(frozen=True)
class CompareViewState:
    """对比页面一次渲染消费的完整状态快照。"""

    phase: ComparePhase
    generation: int
    left_path: Path | None
    right_path: Path | None
    summary: str
    groups: tuple[CompareGroupState, ...]

    @property
    def is_comparing(self) -> bool:
        """Return whether one comparison currently owns the page."""
        return self.phase is ComparePhase.RUNNING


def initial_compare_state() -> CompareViewState:
    """Return the initial empty comparison projection."""
    return CompareViewState(
        phase=ComparePhase.IDLE,
        generation=0,
        left_path=None,
        right_path=None,
        summary="通过侧边栏设置基准存档，再指定目标存档后开始对比。",
        groups=(),
    )


def begin_compare(
    state: CompareViewState,
    left_path: Path,
    right_path: Path,
) -> CompareViewState:
    """Start a new generation and clear the previous projection."""
    return CompareViewState(
        phase=ComparePhase.RUNNING,
        generation=state.generation + 1,
        left_path=left_path,
        right_path=right_path,
        summary="正在对比，请稍候...",
        groups=(),
    )


def complete_compare(
    state: CompareViewState,
    result: WorldCompareResult,
    generation: int,
) -> CompareViewState:
    """Project a matching result, preserving state for stale generations."""
    if generation != state.generation:
        return state
    total = sum(
        value
        for key, value in result.summary.items()
        if key != "changed"
    )
    groups = (
        _build_group("WorldInfo 差异", result.world_info),
        _build_group("玩家数据差异", result.players),
        _build_group("区域文件差异", result.regions),
    )
    return replace(
        state,
        phase=ComparePhase.COMPLETE,
        summary=f"变更项: {result.summary['changed']} / {total}",
        groups=groups,
    )


def fail_compare(
    state: CompareViewState,
    generation: int,
) -> CompareViewState:
    """Project a matching failure without reviving stale operations."""
    if generation != state.generation:
        return state
    return replace(
        state,
        phase=ComparePhase.ERROR,
        summary="对比失败，请检查存档后重试。",
        groups=(),
    )


def invalidate_compare(state: CompareViewState) -> CompareViewState:
    """Invalidate pending callbacks while preserving the latest projection."""
    return replace(
        state,
        phase=ComparePhase.IDLE,
        generation=state.generation + 1,
    )


def _build_group(
    title: str,
    items: Sequence[CompareItem],
) -> CompareGroupState:
    projected = tuple(
        CompareItemState(
            name=item.name,
            left=str(item.left),
            right=str(item.right),
        )
        for item in items
        if not item.same
    )
    return CompareGroupState(title=title, items=projected)


__all__ = [
    "CompareGroupState",
    "CompareItemState",
    "ComparePhase",
    "CompareViewState",
    "begin_compare",
    "complete_compare",
    "fail_compare",
    "initial_compare_state",
    "invalidate_compare",
]
