"""Concurrent batch scheduling with explicit cancellation and task identity."""
from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.cancellable_copy import CopyCancelledError
from core.parallel import (
    ParallelCancelledError,
    ParallelRunner,
    SerialParallelRunner,
    clamp_workers,
)
from core.types import BatchResult, LogCallback, ProgressCallback
from core.utils import validate_world_name


VersionDetector = Callable[[Path], Optional[str]]
BatchTaskHandler = Callable[
    [Path, Path, str, LogCallback, threading.Event],
    Dict[str, Any],
]


class BatchCancelledError(RuntimeError):
    """在安全检查点检测到取消请求时抛出。"""


@dataclass(frozen=True)
class _BatchTask:
    task_id: str
    index: int
    source: Path
    world_name: str


class BatchProcessor:
    """调度彼此独立的世界任务并汇总结构化结果。

    同批任务通过注入的并行端口调度；core 默认实现保持串行且不拥有线程。
    ``stop`` 只请求取消，不伪造运行生命周期。结果键为 ``task-N``，
    单任务失败不中断其余任务聚合。
    """

    MAX_WORKERS = 8

    def __init__(
        self,
        max_workers: Optional[int] = None,
        version_detector: Optional[VersionDetector] = None,
        custom_mappings: Optional[Dict[str, str]] = None,
        task_handler: Optional[BatchTaskHandler] = None,
        runner: Optional[ParallelRunner] = None,
    ) -> None:
        """创建批量处理器。

        Args:
            max_workers: 传给并行端口的最大并发提示，至少为 1；默认 2。
            version_detector: 可选源世界版本探测回调。
            custom_mappings: 完整模式自定义 UUID 映射。
            task_handler: 自定义单世界处理回调；None 时用内置
                fast/full 路径。
            runner: 条目并行端口；默认在当前线程串行执行。
        """
        self.max_workers = clamp_workers(
            max_workers or 2,
            item_count=self.MAX_WORKERS,
            absolute_max=self.MAX_WORKERS,
        )
        self.version_detector = version_detector
        self.custom_mappings = custom_mappings
        self.task_handler = task_handler
        self._runner = runner or SerialParallelRunner()
        self.progress_queue: queue.Queue[Any] = queue.Queue()
        self.results: BatchResult = {}
        self.is_running = False
        self._lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._total_tasks = 0

    def process_batch(
        self,
        world_paths: List[Path],
        dest_dir: Path,
        world_names: Optional[List[str]] = None,
        mode: str = "fast",
        offline_mode: bool = False,
        clean_mode: bool = True,
        pure_clean_mode: bool = False,
        manual_names: Optional[List[str]] = None,
        log_callback: Optional[LogCallback] = None,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> BatchResult:
        """处理每个输入世界一次，并返回按任务键汇总的结果。

        Args:
            world_paths: 源世界路径列表。
            dest_dir: 批量输出目录。
            world_names: 可选目标世界名列表。
            mode: ``fast`` 或 ``full``。
            offline_mode: 离线 UUID 模式。
            clean_mode: 常规清理。
            pure_clean_mode: 纯净清理。
            manual_names: 手动玩家名。
            log_callback: 日志回调。
            progress_callback: 进度回调。

        Returns:
            BatchResult: 任务键到结果字典的映射。

        Raises:
            RuntimeError: 已有批量任务在运行。
        """
        tasks = self._build_tasks(world_paths, world_names, mode)
        self._begin_batch(tasks)
        try:
            if not tasks:
                self._report_empty(log_callback, progress_callback)
                return self.results
            if log_callback:
                log_callback(f"开始批量处理 {len(tasks)} 个存档...", "INFO")
            self._execute_tasks(
                tasks,
                dest_dir,
                mode,
                offline_mode,
                clean_mode,
                pure_clean_mode,
                manual_names,
                log_callback,
                progress_callback,
            )
            self._report_summary(tasks, log_callback)
            return self.results
        finally:
            with self._lock:
                self.is_running = False

    def _begin_batch(self, tasks: list[_BatchTask]) -> None:
        with self._lock:
            if self.is_running:
                raise RuntimeError("批量处理已在运行")
            self.is_running = True
            self.results = {}
            self._total_tasks = len(tasks)
            self._cancel_event.clear()

    def _build_tasks(
        self,
        world_paths: List[Path],
        world_names: Optional[List[str]],
        mode: str,
    ) -> list[_BatchTask]:
        if mode not in {"fast", "full"}:
            raise ValueError(f"不支持的批量处理模式: {mode}")
        names = (
            [f"world_{index + 1}" for index in range(len(world_paths))]
            if world_names is None
            else list(world_names)
        )
        if len(names) != len(world_paths):
            raise ValueError("源存档与目标世界名称数量必须完全一致")
        safe_names = [validate_world_name(name) for name in names]
        if len(set(safe_names)) != len(safe_names):
            raise ValueError("批量任务的目标世界名称不能重复")
        return [
            _BatchTask(
                task_id=f"task-{index + 1}",
                index=index,
                source=Path(source).expanduser().resolve(),
                world_name=safe_names[index],
            )
            for index, source in enumerate(world_paths)
        ]

    def _execute_tasks(
        self,
        tasks: list[_BatchTask],
        dest_dir: Path,
        mode: str,
        offline_mode: bool,
        clean_mode: bool,
        pure_clean_mode: bool,
        manual_names: Optional[List[str]],
        log_callback: Optional[LogCallback],
        progress_callback: Optional[ProgressCallback],
    ) -> None:
        from core.performance import get_tracker

        tracker = get_tracker()
        with tracker.track("批量处理", {"count": str(len(tasks)), "mode": mode}):
            worker = partial(
                self._process_single_world,
                dest_dir=dest_dir,
                mode=mode,
                offline_mode=offline_mode,
                clean_mode=clean_mode,
                pure_clean_mode=pure_clean_mode,
                manual_names=manual_names,
                log_callback=log_callback,
                total_tasks=len(tasks),
            )
            completed = 0
            completion_lock = threading.Lock()

            def on_item_done(
                index: int,
                value: Dict[str, Any] | BaseException,
            ) -> None:
                nonlocal completed
                with completion_lock:
                    completed = self._record_task_completion(
                        tasks[index],
                        value,
                        completed,
                        len(tasks),
                        log_callback,
                        progress_callback,
                    )

            values, cancelled = self._map_tasks(
                tasks,
                worker,
                on_item_done,
            )
            if cancelled:
                with completion_lock:
                    completed = self._record_cancelled_tasks(
                        tasks,
                        len(tasks),
                        log_callback,
                        progress_callback,
                        completed,
                    )
            else:
                self._replay_task_results(tasks, values, on_item_done)

            tracker.increment_files(len(tasks))
            failed = sum(
                1 for result in self.results.values() if not result["success"]
            )
            tracker.add_metadata("success", len(tasks) - failed)
            tracker.add_metadata("failed", failed)
            if failed:
                tracker.increment_errors(failed)

    def _map_tasks(
        self,
        tasks: list[_BatchTask],
        worker: Callable[[_BatchTask], Dict[str, Any]],
        on_item_done: Callable[
            [int, Dict[str, Any] | BaseException],
            None,
        ],
    ) -> tuple[list[Dict[str, Any] | BaseException], bool]:
        """调用并行端口，并把端口级取消转为显式状态。"""
        try:
            values = self._runner.map(
                "batch_world",
                tasks,
                worker,
                max_workers=self.max_workers,
                cancel_check=self._cancel_event.is_set,
                on_item_done=on_item_done,
            )
        except ParallelCancelledError:
            return [], True
        return values, False

    @staticmethod
    def _replay_task_results(
        tasks: list[_BatchTask],
        values: list[Dict[str, Any] | BaseException],
        on_item_done: Callable[
            [int, Dict[str, Any] | BaseException],
            None,
        ],
    ) -> None:
        """补记未通过回调发布的结果，并校验端口等长契约。"""
        if len(values) != len(tasks):
            raise RuntimeError(
                "并行端口返回结果数量与批量任务数量不一致: "
                f"{len(values)} != {len(tasks)}"
            )
        for index, value in enumerate(values):
            on_item_done(index, value)

    def _record_task_completion(
        self,
        task: _BatchTask,
        value: Dict[str, Any] | BaseException,
        completed: int,
        total: int,
        log_callback: Optional[LogCallback],
        progress_callback: Optional[ProgressCallback],
    ) -> int:
        """幂等记录单任务终态，并按完成顺序发布单调进度。"""
        result = self._coerce_task_result(value, task)
        with self._lock:
            if task.task_id in self.results:
                return completed
            self.results[task.task_id] = result
            new_completed = completed + 1
        self._log_task_result(task, result, total, log_callback)
        if progress_callback:
            progress_callback(new_completed / total)
        return new_completed

    def _record_cancelled_tasks(
        self,
        tasks: list[_BatchTask],
        total: int,
        log_callback: Optional[LogCallback],
        progress_callback: Optional[ProgressCallback],
        completed: int,
    ) -> int:
        """为取消后未启动的世界补充结构化终态。"""
        for task in tasks:
            completed = self._record_task_completion(
                task,
                self._cancelled_task_result(task),
                completed,
                total,
                log_callback,
                progress_callback,
            )
        return completed

    @staticmethod
    def _cancelled_task_result(task: _BatchTask) -> Dict[str, Any]:
        """构造尚未完成任务的取消结果。"""
        return {
            "success": False,
            "cancelled": True,
            "error": "批量任务已取消",
            "world_name": task.world_name,
            "source_path": str(task.source),
            "task_index": task.index,
        }

    @classmethod
    def _coerce_task_result(
        cls,
        value: Dict[str, Any] | BaseException,
        task: _BatchTask,
    ) -> Dict[str, Any]:
        """把并行端口的值或异常归一为批量结果。"""
        if isinstance(value, dict):
            return value
        if isinstance(
            value,
            (BatchCancelledError, CopyCancelledError, ParallelCancelledError),
        ):
            return cls._cancelled_task_result(task)
        return {
            "success": False,
            "error": str(value),
            "world_name": task.world_name,
            "source_path": str(task.source),
            "task_index": task.index,
        }

    def _process_single_world(
        self,
        task: _BatchTask,
        dest_dir: Path,
        mode: str,
        offline_mode: bool,
        clean_mode: bool,
        pure_clean_mode: bool,
        manual_names: Optional[List[str]],
        log_callback: Optional[LogCallback],
        total_tasks: int,
    ) -> Dict[str, Any]:
        def local_log(message: str, level: str = "INFO") -> None:
            if log_callback:
                log_callback(
                    f"[{task.index + 1}/{total_tasks}] {message}",
                    level,
                )

        base = {
            "world_name": task.world_name,
            "source_path": str(task.source),
            "task_index": task.index,
        }
        try:
            self._raise_if_cancelled()
            version = self.version_detector(task.source) if self.version_detector else None
            if version:
                local_log(f"检测到版本: {version}", "INFO")
            if self.task_handler:
                result = self.task_handler(
                    task.source,
                    dest_dir,
                    task.world_name,
                    local_log,
                    self._cancel_event,
                )
            else:
                self._run_default_handler(
                    task.source,
                    dest_dir,
                    task.world_name,
                    mode,
                    offline_mode,
                    clean_mode,
                    pure_clean_mode,
                    manual_names,
                    local_log,
                )
                result = {"success": True}
            return {**base, "version": version, **result}
        except (
            BatchCancelledError,
            CopyCancelledError,
            ParallelCancelledError,
        ) as exc:
            return {**base, "success": False, "cancelled": True, "error": str(exc)}
        except RuntimeError as exc:
            if self._cancel_event.is_set():
                return {
                    **base,
                    "success": False,
                    "cancelled": True,
                    "error": str(exc),
                }
            return {**base, "success": False, "error": str(exc)}
        except (OSError, ValueError, TypeError) as exc:
            return {**base, "success": False, "error": str(exc)}
        except Exception as exc:
            # 任务入口边界：单任务失败不影响其余任务聚合。
            return {**base, "success": False, "error": str(exc)}

    def _run_default_handler(
        self,
        source: Path,
        dest_dir: Path,
        world_name: str,
        mode: str,
        offline_mode: bool,
        clean_mode: bool,
        pure_clean_mode: bool,
        manual_names: Optional[List[str]],
        log: LogCallback,
    ) -> None:
        if mode == "fast":
            from core.fast_mode import run_fast

            run_fast(
                source,
                dest_dir,
                world_name,
                offline_mode,
                clean_mode,
                pure_clean_mode,
                manual_names,
                log,
                region_workers=1,
                cancel_check=self._cancel_event.is_set,
            )
            return
        from core.full_mode import run_full
        from core.worker import dummy_progress

        run_full(
            source,
            dest_dir,
            world_name,
            offline_mode,
            clean_mode,
            pure_clean_mode,
            manual_names,
            log,
            dummy_progress,
            self.custom_mappings,
            region_workers=1,
            cancel_check=self._cancel_event.is_set,
        )

    def _log_task_result(
        self,
        task: _BatchTask,
        result: Dict[str, Any],
        total: int,
        callback: Optional[LogCallback],
    ) -> None:
        if not callback:
            return
        if result.get("cancelled"):
            status = "已取消"
            level = "WARNING"
        elif result["success"]:
            status = "成功"
            level = "SUCCESS"
        else:
            status = f"失败: {result.get('error', '未知错误')}"
            level = "ERROR"
        callback(
            f"任务 {task.index + 1}/{total}: {task.world_name} - {status}",
            level,
        )

    def _report_empty(
        self,
        log_callback: Optional[LogCallback],
        progress_callback: Optional[ProgressCallback],
    ) -> None:
        if log_callback:
            log_callback("没有需要处理的存档", "INFO")
        if progress_callback:
            progress_callback(1.0)

    def _report_summary(
        self,
        tasks: list[_BatchTask],
        log_callback: Optional[LogCallback],
    ) -> None:
        if not log_callback:
            return
        success = sum(1 for result in self.results.values() if result["success"])
        cancelled = sum(
            1 for result in self.results.values() if result.get("cancelled")
        )
        level = "SUCCESS" if success == len(tasks) else "WARN"
        log_callback(
            f"批量处理完成: {success}/{len(tasks)} 个存档处理成功"
            f"，取消 {cancelled} 个",
            level,
        )

    def _raise_if_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise BatchCancelledError("批量任务已取消")

    def stop(self) -> None:
        """请求取消进行中的批量任务，不伪造 ``is_running`` 生命周期。"""
        self._cancel_event.set()

    def get_progress(self) -> float:
        """返回已完成任务占比（0.0–1.0）。

        Returns:
            完成数 / 总任务数；无任务时为 0.0。
        """
        with self._lock:
            if self._total_tasks <= 0:
                return 0.0
            return len(self.results) / self._total_tasks


def scan_worlds_directory(directory: Path) -> List[Path]:
    """扫描目录下含 ``level.dat`` 的直接子目录（有效世界）。

    Args:
        directory: 待扫描目录。

    Returns:
        排序后的世界路径列表；目录不存在时为空列表。
    """
    if not directory.exists():
        return []
    worlds = [
        item
        for item in directory.iterdir()
        if item.is_dir() and (item / "level.dat").is_file()
    ]
    return sorted(worlds)
