"""Migration task orchestration with explicit application ports."""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Optional

from app.controllers.migration_lifecycle import (
    MigrationAlreadyRunning,
    MigrationLifecycle,
    MigrationUiPublisher,
    MigrationWorkerAdapter,
    WorkerStarter,
    WorkerTarget,
)
from app.controllers.migration_presenter import (
    MigrationPresentationPorts,
    MigrationResultPresenter,
)
from app.services.config_service import ConfigService
from app.services.execution_runtime import (
    CancellationToken,
    OperationCancelledError,
    OperationHandle,
)
from app.services.migration_service import MigrationService
from core.batch_processor import BatchCancelledError
from core.types import LogCallback, ProgressCallback


Translate = Callable[..., str]
DialogCallback = Callable[..., None]
ExceptionCallback = Callable[..., None]
UiPost = Callable[[Callable[[], None]], None]


def _run_immediately(callback: Callable[[], None]) -> None:
    """Default UI port used by isolated controller tests."""
    callback()


@dataclass(frozen=True)
class MigrationRequest:
    """Immutable configuration captured before a worker is submitted."""

    destination: str
    src_path: str
    world_name: str
    mode: str
    offline: bool
    clean: bool
    pure_clean: bool
    target_platform: str
    target_version: str
    manual_names: str
    batch: bool
    max_concurrent: int
    batch_worlds: tuple[Path, ...] = ()


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
    post_ui: UiPost = _run_immediately


class MigrationController:
    """协调迁移用例，不直接持有 Application 对象。

    Worker callbacks never touch the UI ports directly.  They first pass
    through ``post_ui`` and validate the request generation again when the
    queued callback is executed.
    """

    def __init__(self, dependencies: MigrationControllerDependencies) -> None:
        """初始化控制器。

        Args:
            dependencies: 应用侧显式端口集合。
        """
        self.dependencies = dependencies
        self._lifecycle = MigrationLifecycle[MigrationRequest]()
        self._ui = MigrationUiPublisher(
            self._lifecycle,
            dependencies.post_ui,
        )
        self._presenter = MigrationResultPresenter(
            MigrationPresentationPorts(
                translate=dependencies.translate,
                error_dialog=dependencies.error_dialog,
                handle_exception=dependencies.handle_exception,
                show_success=dependencies.show_success,
                log=dependencies.log,
                log_header=dependencies.log_header,
                set_progress_label=dependencies.set_progress_label,
            ),
            self._ui.publish,
        )

    @property
    def _active_operation(self) -> Optional[OperationHandle[None]]:
        """兼容已有生命周期诊断测试的只读句柄视图。"""
        return self._lifecycle.active_operation

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

    def sync_config_to_migration(self) -> None:
        """将配置服务中的版本检测开关同步到运行时迁移参数。"""
        migration_config = self.config.migration
        migration_config.version_detection = self.config.version_detection

    def start(self) -> None:
        """校验配置并启动单次或批量迁移 worker。"""
        deps = self.dependencies
        reserved = False
        try:
            request = self._capture_request()
            if not request.src_path and not request.batch:
                deps.warn_dialog(
                    self._t("dialogs.warning", "提示"),
                    self._t(
                        "messages.please_select_source",
                        "请先通过侧边栏设置客户端存档目录",
                    ),
                )
                return
            if not request.destination.strip():
                deps.warn_dialog(
                    self._t("dialogs.warning", "提示"),
                    self._t(
                        "messages.please_select_destination",
                        "请先选择目标输出目录",
                    ),
                )
                return

            generation = self._lifecycle.reserve_start()
            reserved = True
            deps.set_start_enabled(False)
            self.try_update_page()
            self.save_config()
            operation_id = (
                "migration_batch" if request.batch else "migration_single"
            )
            self._presenter.start_timing(operation_id)
            worker: WorkerTarget = lambda token: self._run_request(
                request,
                generation,
                token,
            )
            legacy_target = (
                self.run_batch_thread if request.batch else self.run_single_thread
            )
            self._lifecycle.remember_legacy_request(generation, request)
            submission = MigrationWorkerAdapter.submit(
                deps.start_worker,
                operation_id,
                worker,
                legacy_target,
                request.destination,
            )
            if submission.uses_legacy_target:
                # The compatibility target owns its UI completion callback.
                return
            self._install_handle(generation, submission.handle)
        except MigrationAlreadyRunning:
            deps.warn_dialog(
                self._t("dialogs.warning", "提示"),
                self._t(
                    "messages.migration_running",
                    "已有迁移任务正在运行",
                ),
            )
            return
        except Exception as exc:
            if reserved:
                self._rollback_start()
            deps.handle_exception(exc, title="启动转换失败")
            deps.set_start_enabled(True)
            self.try_update_page()

    def _capture_request(self) -> MigrationRequest:
        migration_config = self.config.migration
        worlds = tuple(
            Path(world).expanduser().absolute()
            for world in self.migration.batch_worlds
        )
        return MigrationRequest(
            destination=migration_config.dest_path,
            src_path=migration_config.src_path,
            world_name=migration_config.world_name,
            mode=migration_config.mode,
            offline=migration_config.offline_mode,
            clean=migration_config.clean_mode,
            pure_clean=migration_config.pure_clean_mode,
            target_platform=migration_config.target_platform,
            target_version=migration_config.target_version,
            manual_names=migration_config.manual_names,
            batch=bool(migration_config.batch_mode and worlds),
            max_concurrent=self.config.max_concurrent,
            batch_worlds=worlds,
        )

    def _install_handle(
        self,
        generation: int,
        handle: Optional[OperationHandle[None]],
    ) -> None:
        outcome = self._lifecycle.install_handle(generation, handle)
        if not outcome.accepted:
            self._presenter.clear_timings()
            if outcome.restore_ui:
                self.dependencies.post_ui(self._finish_worker_ui)
            return
        assert handle is not None
        handle.add_done_callback(self._schedule_finish)

    def _rollback_start(self) -> None:
        self._lifecycle.rollback_start()
        self._presenter.clear_timings()

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

    def run_single_thread(
        self,
        destination: str,
        token: Optional[CancellationToken] = None,
    ) -> None:
        """兼容旧 worker 入口；新运行时使用 token 目标闭包。"""
        request, generation = self._legacy_request(destination, batch=False)
        local_token = token or CancellationToken()
        try:
            self._run_request(request, generation, local_token)
        finally:
            self._post_legacy_finish(generation)

    def run_batch_thread(
        self,
        destination: str,
        token: Optional[CancellationToken] = None,
    ) -> None:
        """兼容旧 worker 入口；新运行时使用 token 目标闭包。"""
        request, generation = self._legacy_request(destination, batch=True)
        local_token = token or CancellationToken()
        try:
            self._run_request(request, generation, local_token)
        finally:
            self._post_legacy_finish(generation)

    def _legacy_request(
        self,
        destination: str,
        *,
        batch: bool,
    ) -> tuple[MigrationRequest, int]:
        request, generation = self._lifecycle.resolve_legacy_request(
            lambda stored: stored.destination == destination
        )
        if request is not None:
            return request, generation
        request = self._capture_request()
        if request.batch != batch:
            request = replace(request, batch=batch)
        return request, generation

    def _run_request(
        self,
        request: MigrationRequest,
        generation: int,
        token: CancellationToken,
    ) -> None:
        if request.batch:
            self._run_batch(request, generation, token)
        else:
            self._run_single(request, generation, token)

    def _run_single(
        self,
        request: MigrationRequest,
        generation: int,
        token: CancellationToken,
    ) -> None:
        deps = self.dependencies
        try:
            self._ui.publish(
                generation,
                token,
                deps.log_header,
                self._t("messages.migration_started", "开始迁移任务"),
            )
            output_path = self.migration.run_single(
                src=request.src_path,
                dest=request.destination,
                world_name=request.world_name,
                mode=request.mode,
                offline=request.offline,
                clean=request.clean,
                pure_clean=request.pure_clean,
                target_platform=request.target_platform,
                target_version=request.target_version,
                manual_names_str=request.manual_names,
                log_cb=self._ui.log_callback(
                    generation,
                    token,
                    deps.log,
                ),
                progress_cb=self._ui.progress_callback(
                    generation,
                    token,
                    deps.update_progress,
                ),
                cancel_check=lambda: token.is_cancelled,
            )
            token.raise_if_cancelled()
            self._presenter.single_success(output_path, generation, token)
        except (OperationCancelledError, BatchCancelledError):
            return
        except Exception as exc:
            if token.is_cancelled:
                return
            self._presenter.single_failure(exc, generation, token)

    def _run_batch(
        self,
        request: MigrationRequest,
        generation: int,
        token: CancellationToken,
    ) -> None:
        deps = self.dependencies
        try:
            self._ui.publish(
                generation,
                token,
                deps.log_header,
                self._t("messages.batch_migration_started", "开始批量处理"),
            )
            results = self.migration.run_batch(
                dest_dir=request.destination,
                mode=request.mode,
                offline=request.offline,
                clean=request.clean,
                pure_clean=request.pure_clean,
                target_platform=request.target_platform,
                target_version=request.target_version,
                manual_names_str=request.manual_names,
                max_concurrent=request.max_concurrent,
                log_cb=self._ui.log_callback(
                    generation,
                    token,
                    deps.log,
                ),
                progress_cb=self._ui.progress_callback(
                    generation,
                    token,
                    deps.update_progress,
                ),
                cancel_check=lambda: token.is_cancelled,
                worlds=request.batch_worlds,
            )
            token.raise_if_cancelled()
            self._presenter.batch_success(results, generation, token)
        except (OperationCancelledError, BatchCancelledError):
            return
        except Exception as exc:
            if token.is_cancelled:
                return
            self._presenter.batch_failure(exc, generation, token)

    def _schedule_finish(self, handle: OperationHandle[None]) -> None:
        self.dependencies.post_ui(lambda: self._finish_handle(handle))

    def _finish_handle(self, handle: OperationHandle[None]) -> None:
        should_restore_ui = self._lifecycle.complete_handle(handle)
        if should_restore_ui is None:
            return
        self._presenter.clear_timings()
        if should_restore_ui:
            self._finish_worker_ui()

    def _post_legacy_finish(self, generation: int) -> None:
        self.dependencies.post_ui(lambda: self._finish_legacy(generation))

    def _finish_legacy(self, generation: int) -> None:
        should_restore_ui = self._lifecycle.complete_legacy(generation)
        if should_restore_ui is None:
            return
        self._presenter.clear_timings()
        if should_restore_ui:
            self._finish_worker_ui()

    def _finish_worker_ui(self) -> None:
        """恢复开始按钮与进度条，并刷新页面。"""
        deps = self.dependencies
        deps.set_start_enabled(True)
        deps.set_progress_value(0)
        self.try_update_page()

    def cancel(self) -> bool:
        """同时取消领域迁移与运行时句柄。"""
        outcome = self._lifecycle.request_cancel()
        if not outcome.accepted:
            return False
        self._cancel_domain()
        if outcome.handle is not None:
            outcome.handle.cancel()
        return True

    def close(self) -> None:
        """关闭控制器，取消任务并丢弃迟到回调。"""
        outcome = self._lifecycle.close()
        if not outcome.changed:
            return
        self._presenter.clear_timings()
        if outcome.should_cancel_domain:
            self._cancel_domain()
        if outcome.handle is not None:
            outcome.handle.cancel()

    def open_folder(self, path: str) -> None:
        """在系统文件管理器中打开目录。"""
        self.migration.open_folder(path)

    def _cancel_domain(self) -> None:
        cancel_active = getattr(self.migration, "cancel_active", None)
        if callable(cancel_active):
            cancel_active()
            return
        cancel_batch = getattr(self.migration, "cancel_batch", None)
        if callable(cancel_batch):
            cancel_batch()


__all__ = [
    "MigrationController",
    "MigrationControllerDependencies",
    "MigrationRequest",
]
