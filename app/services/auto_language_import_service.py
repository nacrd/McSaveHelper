"""当前存档切换后的 Minecraft 语言资源自动导入。"""
from __future__ import annotations

import threading
from concurrent.futures import CancelledError
from pathlib import Path
from typing import Callable, Optional

from app.models.save_context import CurrentSaveContext
from app.services.config_service import ConfigService
from app.services.execution_runtime import (
    ExecutionLane,
    ExecutionRuntime,
    OperationCancelledError,
    OperationContext,
    OperationHandle,
    RuntimeClosedError,
    TaskPriority,
    TaskQueueFullError,
)
from app.services.i18n_service import I18nService
from app.services.item.language_loader import LanguageImportResult
from app.services.item_service import ItemService
from core.logger import logger

ImportSuccess = Callable[[LanguageImportResult], None]


class AutoLanguageImportService:
    """调度语言导入，并丢弃存档切换或关闭后的迟到结果。"""

    def __init__(
        self,
        config: ConfigService,
        i18n: I18nService,
        item: ItemService,
        execution_runtime: ExecutionRuntime,
    ) -> None:
        """绑定配置、语言、物品名称表与共享执行运行时。"""
        self._config = config
        self._i18n = i18n
        self._item = item
        self._scope = execution_runtime.create_scope("auto_language_import")
        self._lock = threading.Lock()
        self._generation = 0
        self._save_path: Optional[Path] = None
        self._handle: Optional[OperationHandle[LanguageImportResult]] = None
        self._closed = False

    def schedule(
        self,
        context: CurrentSaveContext,
        on_success: Optional[ImportSuccess] = None,
    ) -> bool:
        """为新选择的存档启动一次后台语言导入。

        Args:
            context: 已选择的当前存档上下文。
            on_success: 成功且仍为当前代次时的回调；在工作线程调用。

        Returns:
            是否成功提交了新任务。
        """
        if self._closed or not self._config.is_auto_import_mc_lang_enabled():
            return False
        save_path = context.path.resolve()
        with self._lock:
            if self._save_path == save_path:
                return False
            self._generation += 1
            generation = self._generation
            self._save_path = save_path
            previous = self._handle
        if previous is not None:
            previous.cancel()
        try:
            handle = self._scope.submit(
                "import_minecraft_language",
                lambda operation: self._import(save_path, operation),
                lane=ExecutionLane.IO,
                priority=TaskPriority.BACKGROUND,
                feature="settings.language",
                world_id=str(save_path),
                generation=generation,
            )
        except (RuntimeClosedError, TaskQueueFullError) as error:
            self._record_failure(save_path, generation, error)
            return False
        with self._lock:
            if self._closed or generation != self._generation:
                handle.cancel()
                return False
            self._handle = handle
        handle.add_done_callback(
            lambda completed: self._finish(
                completed,
                save_path,
                generation,
                on_success,
            )
        )
        return True

    def _import(
        self,
        save_path: Path,
        operation: OperationContext,
    ) -> LanguageImportResult:
        operation.raise_if_cancelled()
        configured = self._config.get_minecraft_dir()
        result = self._item.import_language_from_local_minecraft(
            locale=self._item.normalize_locale(self._i18n.current_language),
            configured_dir=Path(configured) if configured else None,
            start_path=save_path,
        )
        operation.raise_if_cancelled()
        return result

    def _finish(
        self,
        handle: OperationHandle[LanguageImportResult],
        save_path: Path,
        generation: int,
        on_success: Optional[ImportSuccess],
    ) -> None:
        if handle.cancelled:
            return
        try:
            result = handle.result()
        except (CancelledError, OperationCancelledError):
            return
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self._record_failure(save_path, generation, error)
            return
        except Exception as error:
            self._record_failure(save_path, generation, error)
            return
        if not self._is_current(save_path, generation):
            return
        if result.count <= 0:
            logger.warning(
                f"自动导入语言未找到可用文件（locale={result.locale}）",
                module="AutoLanguageImport",
            )
            return
        source = result.sources[0] if result.sources else "unknown"
        logger.info(
            f"已自动导入 Minecraft 语言 {result.count} 项"
            f"（{result.locale}，{source}）",
            module="AutoLanguageImport",
        )
        if on_success is not None:
            on_success(result)

    def _is_current(self, save_path: Path, generation: int) -> bool:
        with self._lock:
            return (
                not self._closed
                and generation == self._generation
                and save_path == self._save_path
            )

    def _record_failure(
        self,
        save_path: Path,
        generation: int,
        error: BaseException,
    ) -> None:
        logger.error(
            f"自动导入 Minecraft 语言失败: {error}",
            module="AutoLanguageImport",
        )
        with self._lock:
            if generation == self._generation and save_path == self._save_path:
                self._save_path = None

    def close(self) -> None:
        """取消活动任务并阻止后续提交；可重复调用。"""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._generation += 1
            handle = self._handle
            self._handle = None
            self._save_path = None
        if handle is not None:
            handle.cancel()
        self._scope.close()


__all__ = ["AutoLanguageImportService", "ImportSuccess"]
