"""Qt 组合根的迁移控制器适配与命令协调。"""
from __future__ import annotations

from typing import Callable, Protocol, cast

from PySide6.QtWidgets import QWidget

from app.controllers.migration_controller import (
    MigrationController,
    MigrationControllerDependencies,
)
from app.qtui.context import QtMigrationCommands
from app.services.config_service import ConfigService
from app.services.execution_runtime import (
    CancellationToken,
    ExecutionLane,
    ExecutionRuntime,
    OperationHandle,
    TaskPriority,
)
from app.services.migration_service import MigrationService


class MigrationCoordinatorHost(Protocol):
    """迁移协调器依赖的 Qt 组合根端口。"""

    @property
    def config(self) -> ConfigService:
        """返回配置服务。"""
        ...

    @property
    def migration(self) -> MigrationService:
        """返回迁移服务。"""
        ...

    @property
    def execution_runtime(self) -> ExecutionRuntime:
        """返回共享执行运行时。"""
        ...

    def translate(self, key: str, default: str = "", **kwargs: object) -> str:
        """翻译 UI 文本。"""
        ...

    def warn_dialog(self, title: str, message: str) -> None:
        """显示警告。"""
        ...

    def error_dialog(
        self,
        title: str,
        message: str,
        exception: Exception | None = None,
        show_details: bool = False,
    ) -> None:
        """显示错误。"""
        ...

    def handle_exception(
        self,
        exception: Exception,
        title: str | None = None,
        log: bool = True,
        show_dialog: bool = True,
    ) -> None:
        """呈现异常。"""
        ...

    def info_dialog(self, title: str, message: str) -> None:
        """显示成功信息。"""
        ...

    def show_status_message(self, message: str, timeout_ms: int = 5000) -> None:
        """显示非阻塞成功反馈。"""
        ...

    def log(self, msg: str, level: str = "INFO") -> None:
        """记录应用日志。"""
        ...

    def pick_directory(self) -> str | None:
        """选择目录。"""
        ...

    def get_migrator_view(self) -> QWidget | None:
        """返回已创建的迁移视图。"""
        ...

    def set_migration_start_enabled(self, enabled: bool) -> None:
        """设置开始迁移命令状态。"""
        ...

    def update_migration_progress(self, value: float) -> None:
        """更新迁移进度。"""
        ...

    def set_migration_progress_label(self, label: str) -> None:
        """更新迁移进度说明。"""
        ...

    def set_migration_progress_value(self, value: float) -> None:
        """更新迁移进度值。"""
        ...

    def post_ui(self, callback: Callable[[], None]) -> None:
        """把回调投递到 Qt 主线程。"""
        ...


class QtMigrationCoordinator:
    """把框架中立迁移控制器接入 Qt 壳层。"""

    def __init__(self, host: MigrationCoordinatorHost) -> None:
        """创建控制器并同步运行时配置。

        Args:
            host: Qt 组合根提供的窄端口。
        """
        self._host = host
        self._controller = MigrationController(
            MigrationControllerDependencies(
                config=host.config,
                migration=host.migration,
                translate=host.translate,
                warn_dialog=host.warn_dialog,
                error_dialog=host.error_dialog,
                handle_exception=host.handle_exception,
                show_success=lambda _title, message: host.show_status_message(
                    message,
                    7000,
                ),
                set_start_enabled=host.set_migration_start_enabled,
                update_page=lambda: None,
                log=host.log,
                log_header=self._log_header,
                update_progress=host.update_migration_progress,
                set_progress_label=host.set_migration_progress_label,
                set_progress_value=host.set_migration_progress_value,
                start_worker=self._start_worker,
                post_ui=host.post_ui,
            )
        )
        self._controller.sync_config_to_migration()

    @property
    def commands(self) -> QtMigrationCommands:
        """返回迁移视图使用的窄命令集合。"""
        return QtMigrationCommands(
            start=self._controller.start,
            cancel=self._controller.cancel,
            choose_destination=self._choose_destination,
            choose_batch_directory=self._choose_batch_directory,
        )

    def close(self) -> None:
        """取消并关闭应用级迁移控制器。"""
        self._controller.close()

    def _choose_destination(self) -> None:
        path = self._host.pick_directory()
        if path:
            self._set_path("destination", path)

    def _choose_batch_directory(self) -> None:
        path = self._host.pick_directory()
        if path:
            self._set_path("batch", path)

    def _set_path(self, target: str, path: str) -> None:
        config = self._host.config.migration
        if target == "destination":
            config.dest_path = path
        else:
            config.batch_dir_path = path
        view = self._host.get_migrator_view()
        setter = getattr(view, "set_path_value", None)
        if callable(setter):
            setter(target, path)

    def _start_worker(
        self,
        operation: str,
        target: Callable[[CancellationToken], None],
    ) -> OperationHandle[None]:
        return cast(
            OperationHandle[None],
            self._host.execution_runtime.submit(
                operation,
                lambda token: self._run_target(target, token),
                lane=ExecutionLane.IO,
                priority=TaskPriority.INTERACTIVE,
            ),
        )

    @staticmethod
    def _run_target(
        target: Callable[[CancellationToken], None],
        token: CancellationToken,
    ) -> None:
        token.raise_if_cancelled()
        target(token)
        token.raise_if_cancelled()

    def _log_header(self, message: str) -> None:
        self._host.log(message, "INFO")


__all__ = ["QtMigrationCoordinator"]
