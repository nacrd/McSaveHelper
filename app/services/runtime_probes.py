"""运行时合成探针：取消与 UI 投递等可测试的验收指标。"""
from __future__ import annotations

import threading
import time
from concurrent.futures import CancelledError
from dataclasses import dataclass
from typing import Callable

from app.services.execution_runtime import (
    CancellationToken,
    ExecutionLane,
    ExecutionRuntime,
    OperationCancelledError,
    TaskPriority,
)
from app.services.operation_progress import OperationState
from app.services.ui_delivery import (
    UiDeliveryChannel,
    UiDeliverySpec,
    UiSchedulePort,
)
from core.observability import OperationOutcome, OperationRecord


@dataclass(frozen=True)
class UiDeliveryProbeResult:
    """一次 UI 投递探针的终态与实际调度耗时。"""

    delivery_id: str
    outcome: OperationOutcome
    queue_wait_ms: float
    run_ms: float
    callback_delivered: bool
    drop_reason: str = ""


def _probe_ui_delivery(
    schedule: UiSchedulePort,
    *,
    is_current: Callable[[], bool],
    clock: Callable[[], int],
    timeout_seconds: float,
) -> UiDeliveryProbeResult:
    """投递一个受 generation 保护的回调并采集其终态。"""
    records: list[OperationRecord] = []
    delivered = threading.Event()
    completed = threading.Event()
    channel = UiDeliveryChannel(schedule, records.append, clock=clock)
    try:
        delivery_id = channel.post(
            UiDeliverySpec(
                task_id="probe-ui-delivery",
                operation="probe_ui_delivery",
                feature="runtime_probe",
                generation=1,
                event="probe",
            ),
            delivered.set,
            is_current=is_current,
            on_complete=completed.set,
        )
        if not completed.wait(timeout_seconds):
            raise TimeoutError("UI 投递探针未能在期限内完成")
        if len(records) != 1:
            raise AssertionError(f"UI 投递探针记录数异常: {len(records)}")
        record = records[0]
        if record.operation_id != delivery_id:
            raise AssertionError("UI 投递探针记录与投递 ID 不一致")
        return UiDeliveryProbeResult(
            delivery_id=delivery_id,
            outcome=record.outcome,
            queue_wait_ms=record.queue_wait_ms,
            run_ms=record.run_ms,
            callback_delivered=delivered.is_set(),
            drop_reason=str(record.metadata.get("drop_reason", "")),
        )
    finally:
        channel.close()


def probe_ui_delivery_latency(
    schedule: UiSchedulePort,
    *,
    clock: Callable[[], int] = time.monotonic_ns,
    timeout_seconds: float = 2.0,
) -> UiDeliveryProbeResult:
    """测量一次有效 UI 投递的队列等待和回调执行耗时。

    Args:
        schedule: 待测的 UI 调度适配器。调用方不得在被阻塞的 UI 线程执行探针。
        clock: 单调纳秒时钟，可注入以进行确定性测试。
        timeout_seconds: 等待调度器完成回调的最长秒数。
    Returns:
        包含真实队列等待、执行耗时与终态的不可变结果。
    Raises:
        TimeoutError: 调度器未在期限内完成投递。
        AssertionError: 调度器未产生唯一成功记录或未执行回调。
    """
    result = _probe_ui_delivery(
        schedule,
        is_current=lambda: True,
        clock=clock,
        timeout_seconds=timeout_seconds,
    )
    if result.outcome is not OperationOutcome.OK or not result.callback_delivered:
        raise AssertionError(f"有效 UI 投递探针终态异常: {result.outcome.value}")
    return result


def probe_stale_ui_delivery(
    schedule: UiSchedulePort,
    *,
    clock: Callable[[], int] = time.monotonic_ns,
    timeout_seconds: float = 2.0,
) -> UiDeliveryProbeResult:
    """验证 generation 过期时 UI 回调被抑制并记录为 ``STALE``。

    Args:
        schedule: 待测的 UI 调度适配器。调用方不得在被阻塞的 UI 线程执行探针。
        clock: 单调纳秒时钟，可注入以进行确定性测试。
        timeout_seconds: 等待调度器完成回调的最长秒数。
    Returns:
        过期投递的不可变结果。
    Raises:
        TimeoutError: 调度器未在期限内完成投递。
        AssertionError: 回调被执行或投递未记录为 generation 过期。
    """
    result = _probe_ui_delivery(
        schedule,
        is_current=lambda: False,
        clock=clock,
        timeout_seconds=timeout_seconds,
    )
    if result.callback_delivered:
        raise AssertionError("过期 UI 投递仍执行了回调")
    if result.outcome is not OperationOutcome.STALE:
        raise AssertionError(f"过期 UI 投递终态异常: {result.outcome.value}")
    if result.drop_reason != "generation_guard":
        raise AssertionError(f"过期 UI 投递原因异常: {result.drop_reason}")
    return result


def probe_cancel_latency_ms(
    runtime: ExecutionRuntime,
    *,
    lane: ExecutionLane = ExecutionLane.CPU,
) -> float:
    """测量「请求取消 → UI 可读状态更新」的毫秒数。

    Args:
        runtime: 共享或测试用运行时。
        lane: 提交通道。
    Returns:
        取消延迟毫秒。

    Raises:
        TimeoutError: 工作未能在合理时间内启动。
        AssertionError: 取消请求未同步更新任务状态。
    """
    started = threading.Event()
    release = threading.Event()

    def work(token: CancellationToken) -> bool:
        started.set()
        release.wait(5.0)
        token.raise_if_cancelled()
        return False

    handle = runtime.submit(
        "probe_cancel_latency",
        work,
        lane=lane,
        priority=TaskPriority.VISIBLE,
    )
    if not started.wait(2.0):
        handle.cancel()
        raise TimeoutError("取消探针工作未能启动")
    t0 = time.perf_counter()
    handle.cancel()
    state = handle.progress().state
    latency_ms = (time.perf_counter() - t0) * 1000.0
    if state is not OperationState.CANCEL_REQUESTED:
        raise AssertionError(f"取消状态未同步发布: {state.value}")
    release.set()
    try:
        handle.result(timeout=1.0)
    except (CancelledError, OperationCancelledError):
        pass
    return latency_ms


def cancel_within_budget(
    runtime: ExecutionRuntime,
    *,
    budget_ms: float = 100.0,
) -> float:
    """执行取消探针并要求延迟不超过预算。

    Returns:
        实测延迟毫秒。

    Raises:
        AssertionError: 超过预算时（供测试使用，消息可读）。
    """
    latency = probe_cancel_latency_ms(runtime)
    if latency > float(budget_ms):
        raise AssertionError(
            f"取消延迟 {latency:.3f}ms 超过预算 {budget_ms:.3f}ms"
        )
    return latency


__all__ = [
    "UiDeliveryProbeResult",
    "cancel_within_budget",
    "probe_cancel_latency_ms",
    "probe_stale_ui_delivery",
    "probe_ui_delivery_latency",
]
