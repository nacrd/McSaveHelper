"""应用级有界、可取消且带优先级的后台任务运行时。"""
from __future__ import annotations

import itertools
import os
import queue
import threading
import time
from collections import Counter
from concurrent.futures import CancelledError, Future
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from types import MappingProxyType
from typing import Callable, Generic, Mapping, Optional, TypeVar, cast
from uuid import uuid4

from core.observability import OperationOutcome, OperationRecord

from app.services.operation_progress import (
    OperationState,
    ProgressReporter,
    ProgressSnapshot,
)


ResultT = TypeVar("ResultT")
OperationRecordSink = Callable[[OperationRecord], None]

# The application owns one runtime.  Keep a process-visible budget for its
# lazily-created lane workers so a permissive per-lane configuration cannot
# silently turn into a thread storm.
DEFAULT_MAX_RUNTIME_WORKERS = 8


class ExecutionLane(str, Enum):
    """后台任务使用的资源通道。"""

    IO = "io"
    CPU = "cpu"


class TaskPriority(IntEnum):
    """任务优先级；数值越小越优先被同一通道的工作线程领取。"""

    VISIBLE = 0
    INTERACTIVE = 1
    BACKGROUND = 2


@dataclass(frozen=True)
class TaskSpec:
    """后台任务描述（文档形态对齐；可选包装 submit 参数）。"""

    operation: str
    lane: ExecutionLane = ExecutionLane.IO
    priority: TaskPriority = TaskPriority.BACKGROUND
    feature: str = "runtime"
    world_id: str = ""
    generation: int = 0
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """拒绝无法形成可观测任务身份的描述。"""
        if not self.operation.strip():
            raise ValueError("后台操作名不能为空")
        if not self.feature.strip():
            raise ValueError("后台功能域不能为空")
        if self.generation < 0:
            raise ValueError("任务 generation 不能为负数")


class TaskQueueFullError(RuntimeError):
    """任务通道达到有界容量时抛出。"""


class RuntimeClosedError(RuntimeError):
    """运行时关闭后继续提交任务时抛出。"""


class OperationCancelledError(RuntimeError):
    """任务在安全检查点观察到取消请求时抛出。"""


@dataclass(frozen=True)
class LaneLimits:
    """一个执行通道的并发与排队限制。

    Attributes:
        max_workers: 同时运行的最大工作线程数。
        queue_capacity: 除运行中任务外允许排队的任务数。
    """

    max_workers: int
    queue_capacity: int

    def __post_init__(self) -> None:
        """校验限制，避免构造无效或无界的执行通道。"""
        if self.max_workers < 1:
            raise ValueError("工作线程数必须至少为 1")
        if self.queue_capacity < 0:
            raise ValueError("排队容量不能为负数")


@dataclass(frozen=True)
class ExecutionRuntimeSnapshot:
    """运行时可观测快照，用于性能面板和验收基准。"""

    active_tasks: int
    active_by_lane: dict[ExecutionLane, int]
    submitted_by_lane: dict[ExecutionLane, int]
    rejected_by_lane: dict[ExecutionLane, int]
    worker_count_by_lane: dict[ExecutionLane, int]
    worker_limit_total: int = 0
    worker_count_total: int = 0
    queue_wait_last_ms: float = 0.0
    queue_wait_max_ms: float = 0.0
    queue_wait_samples: int = 0


class CancellationToken:
    """供后台操作在安全检查点协作取消的线程安全标记。"""

    def __init__(self) -> None:
        """创建尚未取消的标记。"""
        self._event = threading.Event()

    @property
    def is_cancelled(self) -> bool:
        """返回是否已经请求取消。"""
        return self._event.is_set()

    def cancel(self) -> None:
        """请求取消；可重复调用。"""
        self._event.set()

    def wait(self, timeout: Optional[float] = None) -> bool:
        """等待取消请求或超时。

        Args:
            timeout: 最长等待秒数；None 表示持续等待。

        Returns:
            在超时前收到取消请求时返回 True。
        """
        return self._event.wait(timeout)

    def raise_if_cancelled(self) -> None:
        """在已取消时终止当前操作。

        Raises:
            OperationCancelledError: 已收到取消请求。
        """
        if self.is_cancelled:
            raise OperationCancelledError("后台任务已取消")


class _FinalizationBarrier:
    """Allow terminal observers to re-enter ``result`` without deadlocking."""

    def __init__(self, *, completed: bool = False) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._owner_thread_id: Optional[int] = None
        if completed:
            self._event.set()

    def begin(self) -> None:
        """Mark the current thread as the task's finalization owner."""
        with self._lock:
            self._owner_thread_id = threading.get_ident()

    def finish(self) -> None:
        """Release external waiters after terminal progress is committed."""
        with self._lock:
            self._owner_thread_id = None
            self._event.set()

    def wait(self, timeout: Optional[float]) -> bool:
        """Wait unless called re-entrantly by the finalization owner."""
        with self._lock:
            is_owner = self._owner_thread_id == threading.get_ident()
        if is_owner:
            return True
        return self._event.wait(timeout)


class OperationContext(CancellationToken):
    """提交任务时注入的身份、取消和进度端口。"""

    def __init__(
        self,
        task_id: str,
        operation: str,
        feature: str,
        world_id: str,
        generation: int,
        metadata: Mapping[str, object],
        reporter: ProgressReporter,
    ) -> None:
        """绑定任务身份与进度报告器。

        Args:
            task_id: 单次提交的唯一标识。
            operation: 稳定操作名。
            feature: 功能域标识。
            world_id: 可选世界标识。
            generation: 调用方的会话代次。
            metadata: 提交时复制的诊断维度。
            reporter: 线程安全的进度报告器。
        """
        super().__init__()
        self.task_id = task_id
        self.operation = operation
        self.feature = feature
        self.world_id = world_id
        self.generation = generation
        self.metadata = metadata
        self._reporter = reporter

    def cancel(self) -> None:
        """请求协作取消。"""
        self._reporter.mark_cancel_requested()
        super().cancel()

    def report_progress(
        self,
        completed: float,
        total: Optional[float] = None,
        message: str = "",
    ) -> ProgressSnapshot:
        """报告单调进度。

        Args:
            completed: 已完成工作量。
            total: 可选总工作量。
            message: 简短阶段说明。

        Returns:
            发布后的进度快照。
        """
        return self._reporter.update(completed, total, message)

    def progress(self) -> ProgressSnapshot:
        """返回当前进度快照。

        Returns:
            不可变进度快照。
        """
        return self._reporter.snapshot()

    def subscribe_progress(
        self,
        callback: Callable[[ProgressSnapshot], None],
    ) -> Callable[[], None]:
        """订阅进度变化。

        Args:
            callback: 接收不可变快照的轻量回调。

        Returns:
            幂等取消订阅函数。
        """
        return self._reporter.subscribe(callback)

    def mark_stale(self) -> None:
        """将结果标记为不再适用于当前 generation。"""
        self._reporter.mark_stale()


@dataclass(frozen=True, eq=False)
class OperationHandle(Generic[ResultT]):
    """一个已提交后台任务的身份、结果与取消入口。"""

    task_id: str
    operation: str
    feature: str
    world_id: str
    generation: int
    metadata: Mapping[str, object]
    lane: ExecutionLane
    priority: TaskPriority
    _future: Future[ResultT]
    _token: CancellationToken
    _context: OperationContext
    _reporter: ProgressReporter
    _finalized: _FinalizationBarrier

    @property
    def done(self) -> bool:
        """返回任务是否已经结束。"""
        return self._future.done()

    @property
    def cancelled(self) -> bool:
        """返回任务是否以取消作为最终状态结束。"""
        if self._future.cancelled():
            return True
        if not self._future.done():
            return False
        try:
            error = self._future.exception()
        except CancelledError:
            return True
        return isinstance(error, OperationCancelledError)

    @property
    def cancel_requested(self) -> bool:
        """返回任务是否曾收到协作取消请求。"""
        return self._token.is_cancelled

    @property
    def error(self) -> Optional[BaseException]:
        """返回已结束任务的异常。

        Returns:
            原始异常；未结束、成功或取消时返回 ``None``。
        """
        if not self._future.done() or self._future.cancelled():
            return None
        try:
            error = self._future.exception()
        except CancelledError:
            return None
        if isinstance(error, OperationCancelledError):
            return None
        return error

    def progress(self) -> ProgressSnapshot:
        """返回任务当前的不可变进度快照。

        Returns:
            可由 UI 无锁消费的进度快照。
        """
        return self._reporter.snapshot()

    def subscribe_progress(
        self,
        callback: Callable[[ProgressSnapshot], None],
    ) -> Callable[[], None]:
        """订阅任务进度变化。

        Args:
            callback: 接收不可变快照的轻量回调。

        Returns:
            幂等取消订阅函数。
        """
        return self._reporter.subscribe(callback)

    def context(self) -> OperationContext:
        """返回供新业务入口使用的操作上下文。

        Returns:
            当前提交唯一的操作上下文。
        """
        return self._context

    def mark_stale(self) -> None:
        """将尚未交付到当前视图的结果标为过期。"""
        self._reporter.mark_stale()

    def cancel(self) -> bool:
        """请求协作取消，并尝试移除尚未开始的任务。

        Returns:
            本次调用是否对尚未结束的任务发出了取消请求。
        """
        if self._future.done():
            return False
        self._token.cancel()
        self._future.cancel()
        return True

    def result(self, timeout: Optional[float] = None) -> ResultT:
        """等待并返回任务结果。

        Args:
            timeout: 最长等待秒数；None 表示持续等待。

        Returns:
            后台操作返回的值。
        """
        started_at = time.monotonic()
        try:
            return self._future.result(timeout=timeout)
        finally:
            if self._future.done():
                remaining = None
                if timeout is not None:
                    elapsed = time.monotonic() - started_at
                    remaining = max(0.0, timeout - elapsed)
                self._finalized.wait(remaining)

    async def wait_async(self) -> ResultT:
        """在调用方事件循环中异步等待已提交任务。

        不会创建新的工作线程；工作始终仍由提交时选定的运行时通道执行。

        Returns:
            后台操作返回的值。
        """
        import asyncio

        return await asyncio.wrap_future(self._future)

    def add_done_callback(
        self,
        callback: Callable[[OperationHandle[ResultT]], None],
    ) -> None:
        """在任务结束时调用面向句柄的回调。

        Args:
            callback: 接收当前任务句柄的短回调。
        """
        self._future.add_done_callback(lambda future: callback(self))

    @staticmethod
    def completed(
        result: ResultT,
        operation: str,
        *,
        lane: ExecutionLane = ExecutionLane.IO,
        priority: TaskPriority = TaskPriority.BACKGROUND,
        feature: str = "runtime",
        world_id: str = "",
        generation: int = 0,
        metadata: Optional[Mapping[str, object]] = None,
    ) -> OperationHandle[ResultT]:
        """创建无需占用运行时通道的成功句柄。

        Args:
            result: 已完成操作的结果。
            operation: 稳定操作名。
            lane: 诊断用资源通道。
            priority: 诊断用优先级。
            feature: 功能域标识。
            world_id: 可选世界标识。
            generation: 调用方的会话代次。
            metadata: 诊断维度。

        Returns:
            已处于成功终态的操作句柄。
        """
        spec = TaskSpec(
            operation=operation,
            lane=lane,
            priority=priority,
            feature=feature,
            world_id=world_id,
            generation=generation,
            metadata=dict(metadata or {}),
        )
        task_id = uuid4().hex
        selected_metadata = MappingProxyType(dict(spec.metadata))
        reporter = ProgressReporter(task_id, spec.operation, spec.generation)
        reporter.mark_finished(OperationOutcome.OK)
        context = OperationContext(
            task_id,
            spec.operation,
            spec.feature,
            spec.world_id,
            spec.generation,
            selected_metadata,
            reporter,
        )
        future: Future[ResultT] = Future()
        future.set_result(result)
        finalized = _FinalizationBarrier(completed=True)
        return OperationHandle(
            task_id=task_id,
            operation=spec.operation,
            feature=spec.feature,
            world_id=spec.world_id,
            generation=spec.generation,
            metadata=selected_metadata,
            lane=spec.lane,
            priority=spec.priority,
            _future=future,
            _token=context,
            _context=context,
            _reporter=reporter,
            _finalized=finalized,
        )


class OperationScope:
    """拥有一组任务的可关闭生命周期边界。"""

    def __init__(self, runtime: ExecutionRuntime, name: str) -> None:
        """绑定运行时与非空作用域名。"""
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("任务作用域名称不能为空")
        self._runtime = runtime
        self._name = normalized_name
        self._lock = threading.Lock()
        self._closed = False
        self._handles: set[OperationHandle[object]] = set()

    @property
    def active_task_count(self) -> int:
        """返回当前仍由作用域拥有的任务数量。"""
        with self._lock:
            return len(self._handles)

    @property
    def is_closed(self) -> bool:
        """返回作用域是否已经关闭。"""
        with self._lock:
            return self._closed

    def submit(
        self,
        operation: str,
        work: Callable[[OperationContext], ResultT],
        *,
        lane: ExecutionLane = ExecutionLane.IO,
        priority: TaskPriority = TaskPriority.BACKGROUND,
        feature: str = "runtime",
        world_id: str = "",
        generation: int = 0,
        metadata: Optional[Mapping[str, object]] = None,
    ) -> OperationHandle[ResultT]:
        """提交任务，并在任务结束时自动解除所有权登记。"""
        with self._lock:
            if self._closed:
                raise RuntimeClosedError(f"任务作用域已经关闭: {self._name}")
            handle = self._runtime.submit(
                f"{self._name}.{operation}",
                work,
                lane=lane,
                priority=priority,
                feature=feature,
                world_id=world_id,
                generation=generation,
                metadata=metadata,
            )
            tracked = cast(OperationHandle[object], handle)
            self._handles.add(tracked)
        handle.add_done_callback(
            lambda completed: self._discard(
                cast(OperationHandle[object], completed)
            )
        )
        return handle

    def cancel_all(self) -> None:
        """请求取消当前快照中的全部任务，但仍允许后续提交。"""
        with self._lock:
            handles = tuple(self._handles)
        for handle in handles:
            handle.cancel()

    def close(self) -> None:
        """停止接收任务并取消全部现有任务；可重复调用。"""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            handles = tuple(self._handles)
        for handle in handles:
            handle.cancel()

    def _discard(self, handle: OperationHandle[object]) -> None:
        """任务结束回调：移除已经完成的句柄。"""
        with self._lock:
            self._handles.discard(handle)


@dataclass(frozen=True)
class _WorkItem:
    """由优先级队列消费的一个 Future 与可执行函数。"""

    future: Future[object]
    func: Callable[[], object]
    on_dequeued: Callable[[Future[object]], None]


class _PriorityExecutor:
    """最小化的 Future 执行器，保证同通道排队任务按优先级领取。"""

    _SENTINEL_PRIORITY = 99

    def __init__(self, name: str, max_workers: int) -> None:
        """创建惰性启动的固定大小工作线程池。"""
        self._name = name
        self._max_workers = max_workers
        self._queue: queue.PriorityQueue[
            tuple[int, int, Optional[_WorkItem]]
        ] = queue.PriorityQueue()
        self._lock = threading.Lock()
        self._closed = False
        self._sequence = itertools.count()
        self._workers: list[threading.Thread] = []

    @property
    def worker_count(self) -> int:
        """返回已经创建且未退出的工作线程数量。"""
        with self._lock:
            return sum(worker.is_alive() for worker in self._workers)

    @property
    def is_terminated(self) -> bool:
        """返回执行器是否已关闭且全部工作线程已经退出。"""
        with self._lock:
            closed = self._closed
            workers = tuple(self._workers)
        return closed and self._workers_terminated(workers)

    def submit(
        self,
        priority: TaskPriority,
        func: Callable[[], ResultT],
        on_dequeued: Callable[[Future[object]], None],
    ) -> Future[ResultT]:
        """将可执行函数按优先级投入队列。"""
        with self._lock:
            if self._closed:
                raise RuntimeError("执行器已经关闭")
            self._start_workers_locked()
            future: Future[ResultT] = Future()
            item = _WorkItem(
                future=cast(Future[object], future),
                func=cast(Callable[[], object], func),
                on_dequeued=on_dequeued,
            )
            self._queue.put((int(priority), next(self._sequence), item))
            return future

    def _start_workers_locked(self) -> None:
        """首次提交时启动固定数量的命名工作线程。"""
        if self._workers:
            return
        for index in range(self._max_workers):
            worker = threading.Thread(
                target=self._work_loop,
                name=f"{self._name}-{index + 1}",
                daemon=True,
            )
            worker.start()
            self._workers.append(worker)

    def _work_loop(self) -> None:
        """持续取出任务；被取消的 Future 不执行用户函数。"""
        while True:
            _, _, item = self._queue.get()
            try:
                if item is None:
                    return
                item.on_dequeued(item.future)
                if not item.future.set_running_or_notify_cancel():
                    continue
                try:
                    item.future.set_result(item.func())
                except BaseException as exc:
                    item.future.set_exception(exc)
            finally:
                self._queue.task_done()

    def shutdown(
        self,
        *,
        wait: bool,
        cancel_futures: bool,
        timeout: Optional[float] = None,
    ) -> bool:
        """停止接收任务，并按需有界等待工作线程退出。"""
        if timeout is not None and timeout < 0:
            raise ValueError("关闭等待时间不能为负数")
        with self._lock:
            should_close = not self._closed
            if should_close:
                self._closed = True
            workers = tuple(self._workers)

        if should_close:
            if cancel_futures:
                self._cancel_pending_items()
            for _ in workers:
                self._queue.put(
                    (self._SENTINEL_PRIORITY, next(self._sequence), None)
                )
        if wait:
            self._wait_for_workers(workers, timeout)
        return self._workers_terminated(workers)

    @staticmethod
    def _wait_for_workers(
        workers: tuple[threading.Thread, ...],
        timeout: Optional[float],
    ) -> None:
        """使用共享截止时间等待工作线程，且不等待调用线程自身。"""
        deadline = None if timeout is None else time.monotonic() + timeout
        current_worker = threading.current_thread()
        for worker in workers:
            if worker is current_worker:
                continue
            remaining = None
            if deadline is not None:
                remaining = max(0.0, deadline - time.monotonic())
            worker.join(remaining)

    @staticmethod
    def _workers_terminated(workers: tuple[threading.Thread, ...]) -> bool:
        """返回给定工作线程快照是否已经全部退出。"""
        return all(not worker.is_alive() for worker in workers)

    def _cancel_pending_items(self) -> None:
        """取消队列中尚未启动的任务，同时保留关闭哨兵协议。"""
        pending: list[tuple[int, int, Optional[_WorkItem]]] = []
        while True:
            try:
                pending.append(self._queue.get_nowait())
            except queue.Empty:
                break

        for _, _, item in pending:
            try:
                if item is not None:
                    item.on_dequeued(item.future)
                    item.future.cancel()
            finally:
                self._queue.task_done()


@dataclass
class _LaneState:
    """一个执行通道拥有的执行器和容量信号量。"""

    executor: _PriorityExecutor
    capacity: threading.BoundedSemaphore


@dataclass(frozen=True)
class _TrackedTask:
    """运行时登记的任务取消标记和归属通道。"""

    token: CancellationToken
    lane: ExecutionLane


class _TaskAdmission:
    """协调 Future 终态与队列出队，确保容量只释放一次。"""

    def __init__(self) -> None:
        """创建尚未出队且尚未结束的容量占用。"""
        self._lock = threading.Lock()
        self._dequeued = False
        self._future_done = False
        self._released = False

    def mark_dequeued(self) -> bool:
        """记录工作项已经离开底层队列，并返回是否应释放容量。"""
        with self._lock:
            self._dequeued = True
            return self._claim_release_locked()

    def mark_future_done(self) -> bool:
        """记录 Future 已进入终态，并返回是否应释放容量。"""
        with self._lock:
            self._future_done = True
            return self._claim_release_locked()

    def _claim_release_locked(self) -> bool:
        """在持锁时认领唯一一次容量释放。"""
        if self._released or not self._dequeued or not self._future_done:
            return False
        self._released = True
        return True


class _TaskTiming:
    """线程安全地保存一个任务的排队与执行耗时。"""

    def __init__(self) -> None:
        """以构造时刻作为进入运行时队列的时间。"""
        self._enqueued_at = time.perf_counter()
        self._lock = threading.Lock()
        self._started_at: Optional[float] = None
        self._queue_wait_ms = 0.0
        self._run_ms = 0.0

    def mark_started(self) -> float:
        """记录开始执行时刻并返回队列等待毫秒。"""
        started_at = time.perf_counter()
        queue_wait_ms = (started_at - self._enqueued_at) * 1000.0
        with self._lock:
            self._started_at = started_at
            self._queue_wait_ms = max(0.0, queue_wait_ms)
        return self._queue_wait_ms

    def mark_finished(self) -> None:
        """记录工作函数实际运行耗时。"""
        finished_at = time.perf_counter()
        with self._lock:
            if self._started_at is not None:
                self._run_ms = max(
                    0.0,
                    (finished_at - self._started_at) * 1000.0,
                )

    def snapshot(self) -> tuple[float, float]:
        """返回排队与执行毫秒；执行前取消时运行耗时为零。"""
        observed_at = time.perf_counter()
        with self._lock:
            if self._started_at is None:
                queue_wait_ms = (observed_at - self._enqueued_at) * 1000.0
                return max(0.0, queue_wait_ms), 0.0
            return self._queue_wait_ms, self._run_ms


class ExecutionRuntime:
    """统一持有应用后台工作线程、优先级、容量和取消生命周期。"""

    def __init__(
        self,
        io_limits: Optional[LaneLimits] = None,
        cpu_limits: Optional[LaneLimits] = None,
        *,
        total_worker_limit: int = DEFAULT_MAX_RUNTIME_WORKERS,
        operation_sink: Optional[OperationRecordSink] = None,
    ) -> None:
        """创建 I/O 与计算执行通道。

        Args:
            io_limits: I/O 通道限制；默认最多四个工作线程、三十二个排队任务。
            cpu_limits: 计算通道限制；默认最多两个工作线程、八个排队任务。
            total_worker_limit: IO 与 CPU 工作线程数之和的硬上限。
            operation_sink: 可选的统一操作指标接收器；应快速且非阻塞。
        """
        if total_worker_limit < 1:
            raise ValueError("运行时总工作线程上限必须至少为 1")
        cpu_count = os.cpu_count() or 2
        selected_io = io_limits or LaneLimits(
            max_workers=min(4, max(2, cpu_count)),
            queue_capacity=32,
        )
        selected_cpu = cpu_limits or LaneLimits(
            max_workers=min(2, max(1, cpu_count // 2)),
            queue_capacity=8,
        )
        worker_total = selected_io.max_workers + selected_cpu.max_workers
        if worker_total > total_worker_limit:
            raise ValueError(
                "运行时 IO/CPU 工作线程总数超过硬上限: "
                f"{worker_total} > {total_worker_limit}"
            )
        self._lock = threading.Lock()
        self._closed = False
        self._tasks: dict[Future[object], _TrackedTask] = {}
        self._submitted: Counter[ExecutionLane] = Counter()
        self._rejected: Counter[ExecutionLane] = Counter()
        self._queue_wait_last_ms = 0.0
        self._queue_wait_max_ms = 0.0
        self._queue_wait_samples = 0
        self._operation_sink = operation_sink
        self._worker_limit_total = total_worker_limit
        self._lanes = {
            ExecutionLane.IO: self._create_lane("mcsavehelper-io", selected_io),
            ExecutionLane.CPU: self._create_lane(
                "mcsavehelper-cpu",
                selected_cpu,
            ),
        }

    @staticmethod
    def _create_lane(name: str, limits: LaneLimits) -> _LaneState:
        """创建惰性启动线程的有界优先级执行通道。"""
        return _LaneState(
            executor=_PriorityExecutor(name, limits.max_workers),
            capacity=threading.BoundedSemaphore(
                limits.max_workers + limits.queue_capacity
            ),
        )

    @property
    def is_closed(self) -> bool:
        """返回运行时是否已进入关闭状态。"""
        with self._lock:
            return self._closed

    @property
    def is_terminated(self) -> bool:
        """返回运行时是否已关闭且全部工作线程已经退出。"""
        with self._lock:
            closed = self._closed
            executors = tuple(
                state.executor for state in self._lanes.values()
            )
        return closed and all(
            executor.is_terminated for executor in executors
        )

    @property
    def active_task_count(self) -> int:
        """返回运行中与排队中的任务总数。"""
        with self._lock:
            return len(self._tasks)

    def snapshot(self) -> ExecutionRuntimeSnapshot:
        """返回任务、拒绝次数、队列等待与工作线程数的一致快照。"""
        with self._lock:
            active_by_lane = Counter(
                tracked.lane for tracked in self._tasks.values()
            )
            submitted = dict(self._submitted)
            rejected = dict(self._rejected)
            queue_wait_last_ms = self._queue_wait_last_ms
            queue_wait_max_ms = self._queue_wait_max_ms
            queue_wait_samples = self._queue_wait_samples
        return ExecutionRuntimeSnapshot(
            active_tasks=sum(active_by_lane.values()),
            active_by_lane={
                lane: active_by_lane[lane] for lane in ExecutionLane
            },
            submitted_by_lane={
                lane: submitted.get(lane, 0) for lane in ExecutionLane
            },
            rejected_by_lane={
                lane: rejected.get(lane, 0) for lane in ExecutionLane
            },
            worker_count_by_lane={
                lane: state.executor.worker_count
                for lane, state in self._lanes.items()
            },
            worker_limit_total=self._worker_limit_total,
            worker_count_total=sum(
                state.executor.worker_count for state in self._lanes.values()
            ),
            queue_wait_last_ms=queue_wait_last_ms,
            queue_wait_max_ms=queue_wait_max_ms,
            queue_wait_samples=queue_wait_samples,
        )

    def _record_queue_wait_ms(self, wait_ms: float) -> None:
        """记录一次从入队到开始执行的等待时间。"""
        sample = max(0.0, float(wait_ms))
        with self._lock:
            self._queue_wait_last_ms = sample
            self._queue_wait_max_ms = max(self._queue_wait_max_ms, sample)
            self._queue_wait_samples += 1

    def create_scope(self, name: str) -> OperationScope:
        """创建由调用方显式关闭的任务所有权作用域。"""
        if self.is_closed:
            raise RuntimeClosedError("后台任务运行时已经关闭")
        return OperationScope(self, name)

    def submit(
        self,
        operation: str,
        work: Callable[[OperationContext], ResultT],
        *,
        lane: ExecutionLane = ExecutionLane.IO,
        priority: TaskPriority = TaskPriority.BACKGROUND,
        feature: str = "runtime",
        world_id: str = "",
        generation: int = 0,
        metadata: Optional[Mapping[str, object]] = None,
    ) -> OperationHandle[ResultT]:
        """非阻塞地提交一个有身份、优先级和取消标记的后台操作。

        Args:
            operation: 用于日志和诊断的稳定操作名。
            work: 接收取消标记并返回结果的后台函数。
            lane: 操作使用的资源通道。
            priority: 同一通道中可见、交互、后台任务的领取顺序。
            feature: 操作所属功能域。
            world_id: 可选世界身份。
            generation: 调用方维护的视图或会话代次。
            metadata: 可选诊断维度；提交时复制。

        Returns:
            可取消、可等待的任务句柄。

        Raises:
            ValueError: 操作名为空。
            RuntimeClosedError: 运行时已经关闭。
            TaskQueueFullError: 目标通道已经达到容量上限。
        """
        normalized_operation = operation.strip()
        if not normalized_operation:
            raise ValueError("后台操作名不能为空")
        normalized_feature = feature.strip()
        if not normalized_feature:
            raise ValueError("后台功能域不能为空")
        if generation < 0:
            raise ValueError("任务 generation 不能为负数")

        state = self._lanes[lane]
        if not state.capacity.acquire(blocking=False):
            with self._lock:
                self._rejected[lane] += 1
            raise TaskQueueFullError(
                f"后台任务通道已满: {lane.value} [{normalized_operation}]"
            )

        try:
            task_id = uuid4().hex
            selected_metadata = MappingProxyType(dict(metadata or {}))
            reporter = ProgressReporter(
                task_id,
                normalized_operation,
                generation,
            )
            context = OperationContext(
                task_id=task_id,
                operation=normalized_operation,
                feature=normalized_feature,
                world_id=world_id,
                generation=generation,
                metadata=selected_metadata,
                reporter=reporter,
            )
            finalized = _FinalizationBarrier()
            admission = _TaskAdmission()
            timing = _TaskTiming()

            def timed_work(operation_context: OperationContext) -> ResultT:
                wait_ms = timing.mark_started()
                self._record_queue_wait_ms(wait_ms)
                reporter.mark_running()
                try:
                    return work(operation_context)
                finally:
                    timing.mark_finished()

            future = self._submit_locked(
                state,
                lane,
                priority,
                context,
                timed_work,
                admission,
            )
        except Exception:
            state.capacity.release()
            raise

        tracked_future = cast(Future[object], future)

        def release_task(completed: Future[ResultT]) -> None:
            finalized.begin()
            try:
                if admission.mark_future_done():
                    self._release_task(state, tracked_future)
                completed_future = cast(Future[object], completed)
                outcome = self._operation_outcome(completed_future, reporter)
                error = self._future_error(completed_future)
                reporter.mark_finished(outcome, error)
            finally:
                finalized.finish()
            self._publish_operation_record(
                context,
                lane,
                priority,
                timing,
                outcome,
                error,
            )

        future.add_done_callback(release_task)
        return OperationHandle(
            task_id=task_id,
            operation=normalized_operation,
            feature=normalized_feature,
            world_id=world_id,
            generation=generation,
            metadata=selected_metadata,
            lane=lane,
            priority=priority,
            _future=future,
            _token=context,
            _context=context,
            _reporter=reporter,
            _finalized=finalized,
        )

    def submit_spec(
        self,
        spec: TaskSpec,
        work: Callable[[OperationContext], ResultT],
    ) -> OperationHandle[ResultT]:
        """按 ``TaskSpec`` 提交任务（文档形态便捷入口）。"""
        return self.submit(
            spec.operation,
            work,
            lane=spec.lane,
            priority=spec.priority,
            feature=spec.feature,
            world_id=spec.world_id,
            generation=spec.generation,
            metadata=spec.metadata,
        )

    def _submit_locked(
        self,
        state: _LaneState,
        lane: ExecutionLane,
        priority: TaskPriority,
        context: OperationContext,
        work: Callable[[OperationContext], ResultT],
        admission: _TaskAdmission,
    ) -> Future[ResultT]:
        """在关闭锁内提交任务并登记生命周期。"""
        with self._lock:
            if self._closed:
                raise RuntimeClosedError("后台任务运行时已经关闭")
            try:
                future = state.executor.submit(
                    priority,
                    lambda: self._invoke(context, work),
                    lambda dequeued: self._on_task_dequeued(
                        state,
                        admission,
                        dequeued,
                    ),
                )
            except RuntimeError as exc:
                raise RuntimeClosedError("后台任务运行时已经关闭") from exc
            self._tasks[cast(Future[object], future)] = _TrackedTask(
                context,
                lane,
            )
            self._submitted[lane] += 1
            return future

    def _on_task_dequeued(
        self,
        state: _LaneState,
        admission: _TaskAdmission,
        future: Future[object],
    ) -> None:
        """工作项出队后，在 Future 已结束时释放对应容量。"""
        if admission.mark_dequeued():
            self._release_task(state, future)

    @staticmethod
    def _invoke(
        context: OperationContext,
        work: Callable[[OperationContext], ResultT],
    ) -> ResultT:
        """在工作函数开始前执行第一次取消检查。"""
        context.raise_if_cancelled()
        return work(context)

    def _release_task(
        self,
        state: _LaneState,
        future: Future[object],
    ) -> None:
        """任务结束且离开底层队列后释放一个通道容量名额。"""
        with self._lock:
            tracked = self._tasks.pop(future, None)
        if tracked is not None:
            state.capacity.release()

    def _publish_operation_record(
        self,
        context: OperationContext,
        lane: ExecutionLane,
        priority: TaskPriority,
        timing: _TaskTiming,
        outcome: OperationOutcome,
        error: Optional[BaseException],
    ) -> None:
        """向可选接收器发布一次任务终态，不影响任务主要语义。"""
        sink = self._operation_sink
        if sink is None:
            return
        queue_wait_ms, run_ms = timing.snapshot()
        metadata = dict(context.metadata)
        metadata.update(
            {
                "operation": context.operation,
                "lane": lane.value,
                "priority": priority.name.lower(),
                "generation": context.generation,
            }
        )
        if error is not None:
            metadata.update(
                {
                    "error_type": type(error).__name__,
                    "error": str(error)[:500],
                }
            )
        record = OperationRecord(
            operation_id=context.task_id,
            feature=context.feature,
            world_id=context.world_id,
            queue_wait_ms=queue_wait_ms,
            run_ms=run_ms,
            outcome=outcome,
            metadata=metadata,
        )
        try:
            sink(record)
        except Exception:
            # Observability is best-effort and must not change task results.
            pass

    @staticmethod
    def _future_error(future: Future[object]) -> Optional[BaseException]:
        """返回 Future 原始异常；取消和未产生异常时返回 ``None``。"""
        if future.cancelled():
            return None
        try:
            return future.exception()
        except CancelledError:
            return None

    @classmethod
    def _operation_outcome(
        cls,
        future: Future[object],
        reporter: ProgressReporter,
    ) -> OperationOutcome:
        """根据 Future 的真实终态归类成功、错误或协作取消。"""
        if future.cancelled():
            return OperationOutcome.CANCELLED
        error = cls._future_error(future)
        if isinstance(error, OperationCancelledError):
            return OperationOutcome.CANCELLED
        if error is not None:
            return OperationOutcome.ERROR
        if reporter.snapshot().state is OperationState.STALE:
            return OperationOutcome.STALE
        return OperationOutcome.OK

    def shutdown(
        self,
        *,
        wait: bool = False,
        timeout: Optional[float] = None,
    ) -> bool:
        """停止接收任务，取消现有任务并关闭所有执行器。

        Args:
            wait: 是否等待已经开始的工作函数自行结束。
            timeout: 全部执行通道共享的最长等待秒数。

        Returns:
            全部工作线程均已退出时返回 True。

        Raises:
            ValueError: 关闭等待时间为负数。
        """
        if timeout is not None and timeout < 0:
            raise ValueError("关闭等待时间不能为负数")
        deadline = None
        if wait and timeout is not None:
            deadline = time.monotonic() + timeout

        with self._lock:
            should_close = not self._closed
            if should_close:
                self._closed = True
            tasks = tuple(self._tasks.items()) if should_close else ()
            executors = tuple(
                state.executor for state in self._lanes.values()
            )

        for future, tracked in tasks:
            tracked.token.cancel()
            future.cancel()
        terminated = True
        for executor in executors:
            remaining = None
            if deadline is not None:
                remaining = max(0.0, deadline - time.monotonic())
            executor_terminated = executor.shutdown(
                wait=wait,
                cancel_futures=True,
                timeout=remaining,
            )
            terminated = executor_terminated and terminated
        return terminated


__all__ = [
    "CancellationToken",
    "DEFAULT_MAX_RUNTIME_WORKERS",
    "ExecutionLane",
    "ExecutionRuntime",
    "ExecutionRuntimeSnapshot",
    "LaneLimits",
    "OperationContext",
    "OperationCancelledError",
    "OperationHandle",
    "OperationRecordSink",
    "OperationScope",
    "RuntimeClosedError",
    "TaskPriority",
    "TaskQueueFullError",
    "TaskSpec",
]
