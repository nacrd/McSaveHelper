"""应用级有界、可取消且带优先级的后台任务运行时。"""
from __future__ import annotations

import itertools
import os
import queue
import threading
import time
from collections import Counter
from concurrent.futures import Future
from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Callable, Generic, Optional, TypeVar, cast


ResultT = TypeVar("ResultT")


class ExecutionLane(str, Enum):
    """后台任务使用的资源通道。"""

    IO = "io"
    CPU = "cpu"


class TaskPriority(IntEnum):
    """任务优先级；数值越小越优先被同一通道的工作线程领取。"""

    VISIBLE = 0
    INTERACTIVE = 1
    BACKGROUND = 2


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


@dataclass(frozen=True)
class OperationHandle(Generic[ResultT]):
    """一个已提交后台任务的身份、结果与取消入口。"""

    operation: str
    lane: ExecutionLane
    priority: TaskPriority
    _future: Future[ResultT]
    _token: CancellationToken

    @property
    def done(self) -> bool:
        """返回任务是否已经结束。"""
        return self._future.done()

    @property
    def cancelled(self) -> bool:
        """返回任务是否收到取消请求或在执行前被取消。"""
        return self._token.is_cancelled or self._future.cancelled()

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
        return self._future.result(timeout=timeout)

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
        work: Callable[[CancellationToken], ResultT],
        *,
        lane: ExecutionLane = ExecutionLane.IO,
        priority: TaskPriority = TaskPriority.BACKGROUND,
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

    def submit(
        self,
        priority: TaskPriority,
        func: Callable[[], ResultT],
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
                if not item.future.set_running_or_notify_cancel():
                    continue
                try:
                    item.future.set_result(item.func())
                except BaseException as exc:
                    item.future.set_exception(exc)
            finally:
                self._queue.task_done()

    def shutdown(self, *, wait: bool, cancel_futures: bool) -> None:
        """停止接收任务，并按需取消尚未开始的 Future。"""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            workers = tuple(self._workers)

        if cancel_futures:
            self._cancel_pending_items()
        for _ in workers:
            self._queue.put((self._SENTINEL_PRIORITY, next(self._sequence), None))
        if wait:
            for worker in workers:
                worker.join()

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


class ExecutionRuntime:
    """统一持有应用后台工作线程、优先级、容量和取消生命周期。"""

    def __init__(
        self,
        io_limits: Optional[LaneLimits] = None,
        cpu_limits: Optional[LaneLimits] = None,
    ) -> None:
        """创建 I/O 与计算执行通道。

        Args:
            io_limits: I/O 通道限制；默认最多四个工作线程、三十二个排队任务。
            cpu_limits: 计算通道限制；默认最多两个工作线程、八个排队任务。
        """
        cpu_count = os.cpu_count() or 2
        selected_io = io_limits or LaneLimits(
            max_workers=min(4, max(2, cpu_count)),
            queue_capacity=32,
        )
        selected_cpu = cpu_limits or LaneLimits(
            max_workers=min(2, max(1, cpu_count // 2)),
            queue_capacity=8,
        )
        self._lock = threading.Lock()
        self._closed = False
        self._tasks: dict[Future[object], _TrackedTask] = {}
        self._submitted: Counter[ExecutionLane] = Counter()
        self._rejected: Counter[ExecutionLane] = Counter()
        self._queue_wait_last_ms = 0.0
        self._queue_wait_max_ms = 0.0
        self._queue_wait_samples = 0
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
        work: Callable[[CancellationToken], ResultT],
        *,
        lane: ExecutionLane = ExecutionLane.IO,
        priority: TaskPriority = TaskPriority.BACKGROUND,
    ) -> OperationHandle[ResultT]:
        """非阻塞地提交一个有身份、优先级和取消标记的后台操作。

        Args:
            operation: 用于日志和诊断的稳定操作名。
            work: 接收取消标记并返回结果的后台函数。
            lane: 操作使用的资源通道。
            priority: 同一通道中可见、交互、后台任务的领取顺序。

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

        state = self._lanes[lane]
        if not state.capacity.acquire(blocking=False):
            with self._lock:
                self._rejected[lane] += 1
            raise TaskQueueFullError(
                f"后台任务通道已满: {lane.value} [{normalized_operation}]"
            )

        token = CancellationToken()
        enqueued_at = time.perf_counter()

        def timed_work(cancel_token: CancellationToken) -> ResultT:
            wait_ms = (time.perf_counter() - enqueued_at) * 1000.0
            self._record_queue_wait_ms(wait_ms)
            return work(cancel_token)

        try:
            future = self._submit_locked(
                state,
                lane,
                priority,
                token,
                timed_work,
            )
        except Exception:
            state.capacity.release()
            raise

        tracked_future = cast(Future[object], future)

        def release_task(completed: Future[ResultT]) -> None:
            del completed
            self._release_task(state, tracked_future)

        future.add_done_callback(release_task)
        return OperationHandle(
            operation=normalized_operation,
            lane=lane,
            priority=priority,
            _future=future,
            _token=token,
        )

    def _submit_locked(
        self,
        state: _LaneState,
        lane: ExecutionLane,
        priority: TaskPriority,
        token: CancellationToken,
        work: Callable[[CancellationToken], ResultT],
    ) -> Future[ResultT]:
        """在关闭锁内提交任务并登记生命周期。"""
        with self._lock:
            if self._closed:
                raise RuntimeClosedError("后台任务运行时已经关闭")
            try:
                future = state.executor.submit(
                    priority,
                    lambda: self._invoke(token, work),
                )
            except RuntimeError as exc:
                raise RuntimeClosedError("后台任务运行时已经关闭") from exc
            self._tasks[cast(Future[object], future)] = _TrackedTask(token, lane)
            self._submitted[lane] += 1
            return future

    @staticmethod
    def _invoke(
        token: CancellationToken,
        work: Callable[[CancellationToken], ResultT],
    ) -> ResultT:
        """在工作函数开始前执行第一次取消检查。"""
        token.raise_if_cancelled()
        return work(token)

    def _release_task(
        self,
        state: _LaneState,
        future: Future[object],
    ) -> None:
        """任务结束后释放一个通道容量名额。"""
        with self._lock:
            tracked = self._tasks.pop(future, None)
        if tracked is not None:
            state.capacity.release()

    def shutdown(self, *, wait: bool = False) -> None:
        """停止接收任务，取消现有任务并关闭所有执行器。

        Args:
            wait: 是否等待已经开始的工作函数自行结束。
        """
        with self._lock:
            if self._closed:
                return
            self._closed = True
            tasks = tuple(self._tasks.items())
            executors = tuple(
                state.executor for state in self._lanes.values()
            )

        for future, tracked in tasks:
            tracked.token.cancel()
            future.cancel()
        for executor in executors:
            executor.shutdown(wait=wait, cancel_futures=True)


__all__ = [
    "CancellationToken",
    "ExecutionLane",
    "ExecutionRuntime",
    "ExecutionRuntimeSnapshot",
    "LaneLimits",
    "OperationCancelledError",
    "OperationHandle",
    "OperationScope",
    "RuntimeClosedError",
    "TaskPriority",
    "TaskQueueFullError",
]
