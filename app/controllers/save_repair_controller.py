"""存档检测与修复任务的生命周期协调。"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.services.execution_runtime import (
    CancellationToken,
    ExecutionLane,
    OperationCancelledError,
    OperationHandle,
    OperationScope,
    TaskPriority,
)
from app.services.save_repair.models import DetectReport, RepairReport
from app.services.save_repair_service import SaveRepairService


UiPost = Callable[[Callable[[], None]], None]


@dataclass(frozen=True)
class RepairOptions:
    """一次修复任务的不可变选项。"""

    fix_chunks: bool
    fix_players: bool
    fix_level_dat: bool
    backup: bool


@dataclass(frozen=True)
class SaveRepairUiPorts:
    """Controller 向 UI 发布状态的显式端口。"""

    show_progress: Callable[[str], None]
    update_progress: Callable[[str, float], None]
    append_log: Callable[[str, str], None]
    show_detect_report: Callable[[DetectReport], None]
    show_repair_report: Callable[[RepairReport], None]
    show_detect_error: Callable[[Exception], None]
    show_repair_error: Callable[[Exception], None]
    finish_operation: Callable[[], None]


class SaveRepairController:
    """通过共享运行时执行检测/修复并丢弃过期 UI 回调。"""

    def __init__(
        self,
        service: SaveRepairService,
        task_scope: OperationScope,
        ui: SaveRepairUiPorts,
        post_ui: UiPost,
    ) -> None:
        """注入领域服务、共享运行时与 UI 端口。

        Args:
            service: 应用级存档修复服务。
            task_scope: 由视图持有并负责关闭的任务作用域。
            ui: UI 状态发布端口。
            post_ui: 将闭包投递到 UI 线程的调度端口。
        """
        self._service = service
        self._scope = task_scope
        self._ui = ui
        self._post_ui = post_ui
        self._lock = threading.Lock()
        self._generation = 0
        self._world_path: Path | None = None
        self._active: OperationHandle[None] | None = None
        self._closed = False

    def start_detect(self, world_path: Path | str) -> None:
        """提交一次存档检测任务。

        Args:
            world_path: 本次检测绑定的世界路径。
        """
        world = self._path_identity(world_path)
        self._submit("detect_world", world, self._detect_world)

    def start_repair(
        self,
        world_path: Path | str,
        options: RepairOptions,
    ) -> None:
        """提交一次事务化存档修复任务。

        Args:
            world_path: 本次修复绑定的世界路径。
            options: 不可变修复选项。
        """
        world = self._path_identity(world_path)
        self._submit(
            "repair_world",
            world,
            lambda path, generation, token: self._repair_world(
                path,
                options,
                generation,
                token,
            ),
        )

    def select_world(self, world_path: Path | str) -> None:
        """切换世界身份并取消仍属于旧世界的操作。

        Args:
            world_path: 新的当前世界路径。
        """
        self._invalidate(self._path_identity(world_path))

    def cancel(self) -> None:
        """同时取消领域工作与运行时句柄。"""
        self._invalidate(None, preserve_world=True)

    def close(self) -> None:
        """停止回调并取消当前任务；调用方仍负责关闭任务作用域。"""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._generation += 1
            handle = self._active
        self._cancel_handle(handle)

    def _submit(
        self,
        operation: str,
        world_path: Path,
        worker: Callable[[Path, int, CancellationToken], None],
    ) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("存档修复页面已经关闭")
            if self._active is not None and not self._active.done:
                raise RuntimeError("已有存档检测或修复任务正在运行")
            self._generation += 1
            generation = self._generation
            self._world_path = world_path
            handle = self._scope.submit(
                operation,
                lambda token: worker(world_path, generation, token),
                # Orchestration waits for CPU-lane child operations.
                lane=ExecutionLane.IO,
                priority=TaskPriority.INTERACTIVE,
            )
            self._active = handle
        handle.add_done_callback(self._schedule_finish)

    def _invalidate(
        self,
        world_path: Path | None,
        *,
        preserve_world: bool = False,
    ) -> None:
        with self._lock:
            self._generation += 1
            if not preserve_world:
                self._world_path = world_path
            handle = self._active
        self._cancel_handle(handle)

    def _cancel_handle(self, handle: OperationHandle[None] | None) -> None:
        if handle is None or handle.done:
            return
        self._service.cancel()
        handle.cancel()

    def _schedule_finish(self, handle: OperationHandle[None]) -> None:
        self._post_ui(lambda: self._finish(handle))

    def _finish(self, handle: OperationHandle[None]) -> None:
        with self._lock:
            if handle is not self._active:
                return
            self._active = None
            closed = self._closed
        if not closed:
            self._ui.finish_operation()

    def _is_current(
        self,
        generation: int,
        world_path: Path,
        token: CancellationToken,
    ) -> bool:
        with self._lock:
            return (
                not self._closed
                and not token.is_cancelled
                and generation == self._generation
                and world_path == self._world_path
            )

    def _publish(
        self,
        generation: int,
        world_path: Path,
        token: CancellationToken,
        callback: Callable[..., object],
        *args: object,
    ) -> None:
        if not self._is_current(generation, world_path, token):
            return

        def guarded() -> None:
            if self._is_current(generation, world_path, token):
                callback(*args)

        self._post_ui(guarded)

    def _progress_callback(
        self,
        generation: int,
        world_path: Path,
        token: CancellationToken,
        default_message: str,
    ) -> Callable[[float, str], None]:
        def publish_progress(value: float, message: str) -> None:
            self._publish(
                generation,
                world_path,
                token,
                self._ui.update_progress,
                message or default_message,
                value,
            )

        return publish_progress

    def _log_callback(
        self,
        generation: int,
        world_path: Path,
        token: CancellationToken,
    ) -> Callable[[str, str], None]:
        def publish_log(message: str, level: str) -> None:
            self._publish(
                generation,
                world_path,
                token,
                self._ui.append_log,
                message,
                level,
            )

        return publish_log

    def _detect_world(
        self,
        world_path: Path,
        generation: int,
        token: CancellationToken,
    ) -> None:
        try:
            token.raise_if_cancelled()
            self._publish(
                generation,
                world_path,
                token,
                self._ui.show_progress,
                "正在检测存档...",
            )
            report = self._service.detect_world(
                world_path,
                progress_callback=self._progress_callback(
                    generation,
                    world_path,
                    token,
                    "检测中",
                ),
                log_callback=self._log_callback(
                    generation,
                    world_path,
                    token,
                ),
            )
            token.raise_if_cancelled()
            self._publish(
                generation,
                world_path,
                token,
                self._ui.show_detect_report,
                report,
            )
        except OperationCancelledError:
            return
        except Exception as exc:
            self._publish(
                generation,
                world_path,
                token,
                self._ui.show_detect_error,
                exc,
            )

    def _repair_world(
        self,
        world_path: Path,
        options: RepairOptions,
        generation: int,
        token: CancellationToken,
    ) -> None:
        try:
            token.raise_if_cancelled()
            self._publish(
                generation,
                world_path,
                token,
                self._ui.show_progress,
                "正在修复存档...",
            )
            report = self._service.repair_world(
                world_path=world_path,
                fix_chunks=options.fix_chunks,
                fix_players=options.fix_players,
                fix_level_dat=options.fix_level_dat,
                backup=options.backup,
                progress_callback=self._progress_callback(
                    generation,
                    world_path,
                    token,
                    "修复中",
                ),
                log_callback=self._log_callback(
                    generation,
                    world_path,
                    token,
                ),
            )
            token.raise_if_cancelled()
            self._publish(
                generation,
                world_path,
                token,
                self._ui.show_repair_report,
                report,
            )
        except OperationCancelledError:
            return
        except Exception as exc:
            self._publish(
                generation,
                world_path,
                token,
                self._ui.show_repair_error,
                exc,
            )

    @staticmethod
    def _path_identity(path: Path | str) -> Path:
        """规范化比较身份但不访问磁盘。"""
        return Path(path).expanduser().absolute()


__all__ = [
    "RepairOptions",
    "SaveRepairController",
    "SaveRepairUiPorts",
]
