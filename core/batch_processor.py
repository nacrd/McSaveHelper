"""Concurrent batch scheduling with explicit cancellation and task identity."""
from __future__ import annotations

import queue
import threading
from concurrent.futures import (
    CancelledError,
    Future,
    ThreadPoolExecutor,
    as_completed,
)
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.types import BatchResult, LogCallback, ProgressCallback
from core.utils import validate_world_name


VersionDetector = Callable[[Path], Optional[str]]
BatchTaskHandler = Callable[
    [Path, Path, str, LogCallback, threading.Event],
    Dict[str, Any],
]


class BatchCancelledError(RuntimeError):
    """Raised at a safe checkpoint when cancellation was requested."""


@dataclass(frozen=True)
class _BatchTask:
    task_id: str
    index: int
    source: Path
    world_name: str


class BatchProcessor:
    """Schedule independent world tasks and aggregate structured results."""

    def __init__(
        self,
        max_workers: Optional[int] = None,
        version_detector: Optional[VersionDetector] = None,
        custom_mappings: Optional[Dict[str, str]] = None,
        task_handler: Optional[BatchTaskHandler] = None,
    ) -> None:
        self.max_workers = max(1, max_workers or 2)
        self.version_detector = version_detector
        self.custom_mappings = custom_mappings
        self.task_handler = task_handler
        self.progress_queue: queue.Queue[Any] = queue.Queue()
        self.results: BatchResult = {}
        self.is_running = False
        self._lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._futures: set[Future[Dict[str, Any]]] = set()
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
        """Process each input exactly once and return task-keyed results."""
        tasks = self._build_tasks(world_paths, world_names, mode)
        with self._lock:
            if self.is_running:
                raise RuntimeError("批量处理已在运行")
            self.is_running = True
            self.results = {}
            self._total_tasks = len(tasks)
            self._futures = set()
            self._cancel_event.clear()

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
                self._futures.clear()

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
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                future_tasks: dict[Future[Dict[str, Any]], _BatchTask] = {}
                for task in tasks:
                    future = executor.submit(
                        self._process_single_world,
                        task,
                        dest_dir,
                        mode,
                        offline_mode,
                        clean_mode,
                        pure_clean_mode,
                        manual_names,
                        log_callback,
                        len(tasks),
                    )
                    future_tasks[future] = task
                with self._lock:
                    self._futures = set(future_tasks)

                completed = 0
                for future in as_completed(future_tasks):
                    if self._cancel_event.is_set():
                        self._cancel_pending()
                    task = future_tasks[future]
                    result = self._future_result(future, task)
                    with self._lock:
                        self.results[task.task_id] = result
                        completed += 1
                    self._log_task_result(task, result, len(tasks), log_callback)
                    if progress_callback:
                        progress_callback(completed / len(tasks))

            tracker.increment_files(len(tasks))
            failed = sum(1 for result in self.results.values() if not result["success"])
            tracker.add_metadata("success", len(tasks) - failed)
            tracker.add_metadata("failed", failed)
            if failed:
                tracker.increment_errors(failed)

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
        except BatchCancelledError as exc:
            return {**base, "success": False, "cancelled": True, "error": str(exc)}
        except Exception as exc:
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
        )

    def _future_result(
        self,
        future: Future[Dict[str, Any]],
        task: _BatchTask,
    ) -> Dict[str, Any]:
        try:
            return future.result()
        except CancelledError:
            return {
                "success": False,
                "cancelled": True,
                "error": "批量任务已取消",
                "world_name": task.world_name,
                "source_path": str(task.source),
                "task_index": task.index,
            }
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "world_name": task.world_name,
                "source_path": str(task.source),
                "task_index": task.index,
            }

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

    def _cancel_pending(self) -> None:
        with self._lock:
            futures = tuple(self._futures)
        for future in futures:
            future.cancel()

    def stop(self) -> None:
        """Request cancellation without falsifying the running lifecycle."""
        self._cancel_event.set()
        self._cancel_pending()

    def get_progress(self) -> float:
        with self._lock:
            if self._total_tasks <= 0:
                return 0.0
            return len(self.results) / self._total_tasks


def scan_worlds_directory(directory: Path) -> List[Path]:
    """Return direct child directories containing a level.dat file."""
    if not directory.exists():
        return []
    worlds = [
        item
        for item in directory.iterdir()
        if item.is_dir() and (item / "level.dat").is_file()
    ]
    return sorted(worlds)
