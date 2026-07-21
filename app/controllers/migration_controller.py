"""Migration task orchestration with explicit application ports."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from app.services.config_service import ConfigService
from app.services.migration_service import MigrationService
from core.types import LogCallback, ProgressCallback


Translate = Callable[..., str]
DialogCallback = Callable[..., None]
ExceptionCallback = Callable[..., None]
WorkerTarget = Callable[[str], None]
WorkerHandle = Any
WorkerStarter = Callable[[str, WorkerTarget, str], WorkerHandle]


@dataclass(frozen=True)
class MigrationControllerDependencies:
    """迁移控制器依赖端口。"""

    config: ConfigService
    migration: MigrationService
    translate: Translate
    warn_dialog: DialogCallback
    error_dialog: DialogCallback
    handle_exception: ExceptionCallback
    show_success: Callable[[str, str], None]
    set_start_enabled: Callable[[bool], None]
    update_page: Callable[[], None]
    log: LogCallback
    log_header: Callable[[str], None]
    update_progress: ProgressCallback
    set_progress_label: Callable[[str], None]
    set_progress_value: Callable[[float], None]
    start_worker: WorkerStarter


class MigrationController:
    """协调迁移用例，不直接持有 Application 对象。"""

    def __init__(self, dependencies: MigrationControllerDependencies) -> None:
        """初始化控制器。

        Args:
            dependencies: 应用侧显式端口集合。
        """
        self.dependencies = dependencies
        self._operation_started_at: dict[str, float] = {}
        self._active_operation: Optional[WorkerHandle] = None

    @property
    def config(self) -> ConfigService:
        """配置服务快捷访问。"""
        return self.dependencies.config

    @property
    def migration(self) -> MigrationService:
        """迁移服务快捷访问。"""
        return self.dependencies.migration

    def _t(self, key: str, default: str = "", **kwargs: Any) -> str:
        return self.dependencies.translate(key, default, **kwargs)

    def _start_timing(self, operation_id: str) -> None:
        self._operation_started_at[operation_id] = time.monotonic()

    def _finish_timing(self, operation_id: str) -> float | None:
        started_at = self._operation_started_at.pop(operation_id, None)
        if started_at is None:
            return None
        return time.monotonic() - started_at

    def sync_config_to_migration(self) -> None:
        """将配置服务中的版本检测开关同步到运行时迁移参数。"""
        migration_config = self.config.migration
        migration_config.version_detection = self.config.version_detection

    def start(self) -> None:
        """校验配置并启动单次或批量迁移 worker。"""
        deps = self.dependencies
        try:
            migration_config = self.config.migration
            if not migration_config.src_path and not migration_config.batch_mode:
                deps.warn_dialog(
                    self._t("dialogs.warning", "提示"),
                    self._t(
                        "messages.please_select_source",
                        "请先通过侧边栏设置客户端存档目录",
                    ),
                )
                return
            if not migration_config.dest_path.strip():
                deps.warn_dialog(
                    self._t("dialogs.warning", "提示"),
                    self._t(
                        "messages.please_select_destination",
                        "请先选择目标输出目录",
                    ),
                )
                return

            deps.set_start_enabled(False)
            self.try_update_page()
            self.save_config()
            destination = migration_config.dest_path
            run_batch = (
                migration_config.batch_mode
                and bool(self.migration.batch_worlds)
            )
            operation_id = (
                "migration_batch" if run_batch else "migration_single"
            )
            self._start_timing(operation_id)
            target = (
                self.run_batch_thread if run_batch else self.run_single_thread
            )
            self._active_operation = deps.start_worker(
                operation_id,
                target,
                destination,
            )
        except Exception as exc:
            # UI 入口边界：恢复按钮并使能。
            deps.handle_exception(exc, title="启动转换失败")
            deps.set_start_enabled(True)
            self.try_update_page()

    def try_update_page(self) -> None:
        """尽力刷新页面；关闭中或未挂载时静默跳过。"""
        try:
            self.dependencies.update_page()
        except RuntimeError:
            pass

    def save_config(self) -> None:
        """将批量相关配置写回持久化层。"""
        migration_config = self.config.migration
        self.config.update_batch_config(
            version_detection=migration_config.version_detection,
            max_concurrent=self.config.max_concurrent,
            custom_uuid_mappings=self.config.custom_uuid_mappings,
            use_custom_mapping=self.config.use_custom_mapping,
        )

    def run_single_thread(self, destination: str) -> None:
        """后台线程：执行单存档迁移并反馈 UI。

        Args:
            destination: 目标输出目录。
        """
        deps = self.dependencies
        migration_config = self.config.migration
        try:
            deps.log_header(
                self._t("messages.migration_started", "开始迁移任务")
            )
            output_path = self.migration.run_single(
                src=migration_config.src_path,
                dest=destination,
                world_name=migration_config.world_name,
                mode=migration_config.mode,
                offline=migration_config.offline_mode,
                clean=migration_config.clean_mode,
                pure_clean=migration_config.pure_clean_mode,
                target_platform=migration_config.target_platform,
                target_version=migration_config.target_version,
                manual_names_str=migration_config.manual_names,
                log_cb=deps.log,
                progress_cb=deps.update_progress,
            )
            self._report_single_success(output_path)
        except Exception as exc:
            self._report_single_failure(exc)
        finally:
            self._finish_worker_ui()

    def run_batch_thread(self, destination: str) -> None:
        """后台线程：执行批量迁移并反馈 UI。

        Args:
            destination: 批量目标输出目录。
        """
        deps = self.dependencies
        migration_config = self.config.migration
        try:
            deps.log_header(
                self._t("messages.batch_migration_started", "开始批量处理")
            )
            self.save_config()
            results = self.migration.run_batch(
                dest_dir=destination,
                mode=migration_config.mode,
                offline=migration_config.offline_mode,
                clean=migration_config.clean_mode,
                pure_clean=migration_config.pure_clean_mode,
                target_platform=migration_config.target_platform,
                target_version=migration_config.target_version,
                manual_names_str=migration_config.manual_names,
                max_concurrent=self.config.max_concurrent,
                log_cb=deps.log,
                progress_cb=deps.update_progress,
            )
            self._report_batch_success(results)
        except Exception as exc:
            self._report_batch_failure(exc)
        finally:
            self._finish_worker_ui()

    def _report_single_success(self, output_path: str) -> None:
        deps = self.dependencies
        elapsed = self._finish_timing("migration_single")
        if elapsed is not None:
            deps.log(f"迁移耗时: {elapsed:.2f}秒", "INFO")
        deps.log_header(self._t("messages.migration_complete", "迁移完成"))
        success_message = self._t(
            "messages.migration_success",
            "迁移完成！输出目录: {output_path}",
            output_path=output_path,
        )
        deps.log(success_message, "SUCCESS")
        deps.set_progress_label(self._t("top_bar.completed", "已完成"))
        deps.show_success(
            self._t("dialogs.success", "成功"),
            success_message,
        )

    def _report_single_failure(self, exc: BaseException) -> None:
        deps = self.dependencies
        self._finish_timing("migration_single")
        error_message = self._t(
            "messages.migration_exception",
            "迁移失败: {error}",
            error=str(exc),
        )
        deps.handle_exception(
            exc,
            title=error_message,
            log=True,
            show_dialog=False,
        )
        deps.set_progress_label(self._t("top_bar.failed", "失败"))
        deps.error_dialog(
            self._t("dialogs.error", "错误"),
            error_message,
            exception=exc,
            show_details=True,
        )

    def _report_batch_success(self, results: dict[str, Any]) -> None:
        deps = self.dependencies
        elapsed = self._finish_timing("migration_batch")
        if elapsed is not None:
            deps.log(f"批量迁移耗时: {elapsed:.2f}秒", "INFO")
        success = sum(1 for result in results.values() if result["success"])
        cancelled = sum(
            1 for result in results.values() if result.get("cancelled")
        )
        failed = len(results) - success - cancelled
        deps.log_header(
            self._t(
                "messages.batch_migration_complete_header",
                "批量处理完成",
            )
        )
        deps.log(
            self._t(
                "messages.batch_migration_complete",
                "成功: {success}/{total}",
                success=success,
                total=len(results),
            ),
            "SUCCESS" if success == len(results) else "WARN",
        )
        if success == len(results):
            label = self._t("top_bar.batch_completed", "批量处理完成")
        else:
            label = self._t(
                "top_bar.batch_partial",
                "批量处理部分完成",
            )
            deps.log(
                self._t(
                    "messages.batch_result_details",
                    "失败: {failed}，取消: {cancelled}",
                    failed=failed,
                    cancelled=cancelled,
                ),
                "WARN",
            )
        deps.set_progress_label(label)

    def _report_batch_failure(self, exc: BaseException) -> None:
        deps = self.dependencies
        self._finish_timing("migration_batch")
        deps.handle_exception(
            exc,
            title=self._t(
                "messages.save_failed",
                "批量处理失败: {error}",
                error=str(exc),
            ),
            log=True,
            show_dialog=False,
        )
        deps.set_progress_label(
            self._t("top_bar.batch_failed", "批量处理失败")
        )

    def _finish_worker_ui(self) -> None:
        """恢复开始按钮与进度条，并刷新页面。"""
        deps = self.dependencies
        deps.set_start_enabled(True)
        deps.set_progress_value(0)
        self.try_update_page()

    def open_folder(self, path: str) -> None:
        """在系统文件管理器中打开目录。"""
        self.migration.open_folder(path)
