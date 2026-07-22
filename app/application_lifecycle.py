"""Application lifecycle helpers extracted from the composition root."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable, Optional, cast

from app.models.save_context import CurrentSaveContext
from app.services.execution_runtime import (
    CancellationToken,
    OperationHandle,
    RuntimeClosedError,
    TaskQueueFullError,
)
from app.ui.utils import run_on_ui


class AutoLanguageImportSupport:
    """Mixin: schedule Minecraft language import after save selection."""

    config: Any
    item: Any
    i18n: Any
    execution_runtime: Any
    page: Any
    gui_optimizer: Any
    log: Any
    _t: Any
    _auto_lang_import_path: Optional[str]
    _auto_lang_import_generation: int
    _auto_lang_import_lock: threading.Lock
    _auto_lang_import_task: Optional[OperationHandle[None]]

    def _init_auto_language_import_state(self) -> None:
        self._auto_lang_import_path = None
        self._auto_lang_import_generation = 0
        self._auto_lang_import_lock = threading.Lock()
        self._auto_lang_import_task = None

    def _schedule_auto_import_mc_language(
        self,
        context: CurrentSaveContext,
    ) -> None:
        if not self.config.is_auto_import_mc_lang_enabled():
            return
        save_path = str(context.path).strip()
        if not save_path:
            return
        with self._auto_lang_import_lock:
            if self._auto_lang_import_path == save_path:
                return
            self._auto_lang_import_path = save_path
            self._auto_lang_import_generation += 1
            generation = self._auto_lang_import_generation
        previous_task = self._auto_lang_import_task
        if previous_task is not None:
            previous_task.cancel()
        try:
            self._auto_lang_import_task = self.execution_runtime.submit(
                "auto_import_minecraft_language",
                lambda token: self._auto_import_mc_language_worker(
                    save_path,
                    generation,
                    token,
                ),
            )
        except (RuntimeClosedError, TaskQueueFullError) as exc:
            self._handle_auto_import_failure(save_path, generation, exc)

    def _auto_import_mc_language_worker(
        self,
        save_path: str,
        generation: int,
        cancellation: Optional[CancellationToken] = None,
    ) -> None:
        if cancellation is not None and cancellation.is_cancelled:
            return
        try:
            locale = self.item.normalize_locale(self.i18n.current_language)
            configured = self.config.get_minecraft_dir()
            configured_dir = Path(configured) if configured else None
            result = self.item.import_language_from_local_minecraft(
                locale=locale,
                configured_dir=configured_dir,
                start_path=Path(save_path),
            )
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            self._handle_auto_import_failure(save_path, generation, exc)
            return
        except Exception as exc:
            self._handle_auto_import_failure(save_path, generation, exc)
            return
        if (
            cancellation is not None
            and cancellation.is_cancelled
        ) or not self._is_auto_import_current(save_path, generation):
            return
        if result.count <= 0:
            self.log(
                f"自动导入语言未找到可用文件（locale={locale}）",
                "WARN",
            )
            return
        source = result.sources[0] if result.sources else "unknown"
        self.log(
            f"已自动导入 Minecraft 语言 {result.count} 项"
            f"（{result.locale}，{source}）",
            "INFO",
        )
        message = self._t(
            "settings.auto_import_mc_lang_ok",
            "已自动导入 {count} 个 Minecraft 名称（{locale}）",
            count=result.count,
            locale=result.locale,
        )
        run_on_ui(self.page, self._notify_auto_import_success, message)

    def _is_auto_import_current(
        self,
        save_path: str,
        generation: int,
    ) -> bool:
        with self._auto_lang_import_lock:
            return (
                self._auto_lang_import_generation == generation
                and self._auto_lang_import_path == save_path
            )

    def _handle_auto_import_failure(
        self,
        save_path: str,
        generation: int,
        exc: BaseException,
    ) -> None:
        self.log(f"自动导入 Minecraft 语言失败: {exc}", "ERROR")
        with self._auto_lang_import_lock:
            if (
                self._auto_lang_import_generation == generation
                and self._auto_lang_import_path == save_path
            ):
                self._auto_lang_import_path = None

    def _notify_auto_import_success(self, message: str) -> None:
        notification_manager = self.gui_optimizer.notification_manager
        if notification_manager is not None:
            notification_manager.show_success(message)


class MigrationRuntimeSupport:
    """Mixin: migration worker scheduling through ExecutionRuntime."""

    execution_runtime: Any

    def _start_migration_worker(
        self,
        operation: str,
        target: Callable[[str], None],
        destination: str,
    ) -> OperationHandle[None]:
        from app.services.execution_runtime import ExecutionLane, TaskPriority

        return cast(
            OperationHandle[None],
            self.execution_runtime.submit(
                operation,
                lambda cancellation: self._run_migration_target(
                    target,
                    destination,
                    cancellation,
                ),
                lane=ExecutionLane.CPU,
                priority=TaskPriority.INTERACTIVE,
            ),
        )

    @staticmethod
    def _run_migration_target(
        target: Callable[[str], None],
        destination: str,
        cancellation: CancellationToken,
    ) -> None:
        cancellation.raise_if_cancelled()
        target(destination)
        cancellation.raise_if_cancelled()


__all__ = [
    "AutoLanguageImportSupport",
    "MigrationRuntimeSupport",
]
