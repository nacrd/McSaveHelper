"""纯 UI 更新预算探针（不依赖 Flet 帧循环）。

设计验收要求单次 UI 更新预算 16 ms；本模块对代表性纯工作样本
计时，供单元测试与合成门禁使用。
"""
from __future__ import annotations

import time
from typing import Callable


UI_FRAME_BUDGET_MS = 16.0


class UiBudgetExceededError(RuntimeError):
    """纯工作样本超过 UI 帧预算时抛出。"""


def measure_work_ms(work: Callable[[], object]) -> float:
    """执行 ``work`` 并返回耗时毫秒。"""
    started = time.perf_counter()
    work()
    return (time.perf_counter() - started) * 1000.0


def within_ui_budget(
    elapsed_ms: float,
    *,
    budget_ms: float = UI_FRAME_BUDGET_MS,
) -> bool:
    """判断耗时是否在预算内。"""
    return float(elapsed_ms) <= float(budget_ms)


def assert_within_ui_budget(
    work: Callable[[], object],
    *,
    budget_ms: float = UI_FRAME_BUDGET_MS,
) -> float:
    """执行工作；超时则抛出 ``UiBudgetExceededError``。

    Returns:
        实际耗时毫秒。
    """
    elapsed = measure_work_ms(work)
    if not within_ui_budget(elapsed, budget_ms=budget_ms):
        raise UiBudgetExceededError(
            f"UI 工作耗时 {elapsed:.3f}ms 超过预算 {budget_ms:.3f}ms"
        )
    return elapsed


__all__ = [
    "UI_FRAME_BUDGET_MS",
    "UiBudgetExceededError",
    "assert_within_ui_budget",
    "measure_work_ms",
    "within_ui_budget",
]
