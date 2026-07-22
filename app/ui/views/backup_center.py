"""Managed backup and restore center."""
from __future__ import annotations

from concurrent.futures import CancelledError
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

import flet as ft

from app.controllers.backup_operation_controller import (
    BackupOperationBusyError,
    BackupOperationController,
    BackupOperationRequest,
    BackupOperationUiPorts,
)
from app.services.backup_service import (
    BackupError,
    BackupRecord,
    BackupService,
    BackupVerification,
)
from app.services.execution_runtime import (
    CancellationToken,
    OperationCancelledError,
    OperationHandle,
    ExecutionLane,
    TaskPriority,
)
from app.ui.components.buttons import btn_danger, btn_primary
from app.ui.components.cards import card, placeholder
from app.ui.components.fields import current_save_field, dropdown, text_field
from app.ui.components.layout import page_header, section_header
from app.ui.icons import IconSet
from app.ui.theme import THEME, mc_border
from app.ui.utils import format_size, run_on_ui, safe_update
from app.ui.view_actions import ViewAction

if TYPE_CHECKING:
    from app.ui.feature_context import FeatureContext


class BackupCenterView(ft.Column):
    """Create, inspect, restore, and remove managed world snapshots."""

    def __init__(
        self,
        app: "FeatureContext",
        service: Optional[BackupService] = None,
    ) -> None:
        """初始化备份中心视图。

        Args:
            app: 应用组合根。
            service: 可选备份服务；缺省使用 ``app.services.backup``。
        """
        super().__init__(spacing=18, scroll=ft.ScrollMode.AUTO, expand=True)
        self.app = app
        self.service = service or app.services.backup
        self._task_scope = app.execution_runtime.create_scope("backup_center_view")
        self._busy = False
        self._refresh_generation = 0
        self._build_ui()
        self._operation_controller = BackupOperationController(
            self._task_scope,
            BackupOperationUiPorts(
                dispatch=lambda callback: self._post_to_ui(callback),
                get_world_path=self._current_world_path,
                show_progress=lambda task: self.app.show_progress(task),
                update_progress=lambda task, value: self.app.update_progress_with_task(
                    task, value
                ),
                hide_progress=lambda: self.app.hide_progress(),
                set_busy=self._set_busy,
                set_cancel_pending=self._set_cancel_pending,
            ),
        )

    def _t(self, key: str, default: str) -> str:
        return self.app.translate(f"backup_center.{key}", default)

    def get_top_actions(self) -> list[ViewAction]:
        """Keep creation next to its form instead of duplicating it."""
        return []

    def _build_ui(self) -> None:
        self._build_backup_fields()
        self._page_header = page_header(
            self._t("title", "备份与恢复"),
            ft.Text(
                self._t("subtitle", "管理完整世界快照和恢复点"),
                size=12,
                color=THEME.text_muted,
            ),
            icon=IconSet.HISTORY,
            actions=ft.IconButton(
                icon=IconSet.REFRESH,
                tooltip=self._t("refresh", "刷新备份列表"),
                icon_color=THEME.text_primary,
                on_click=self._refresh,
            ),
        )
        create_panel = card(
            ft.Column(
                [
                    self._world_path_field,
                    self._label_field,
                    ft.Row(
                        [self._create_button, self._cancel_button],
                        spacing=10,
                        scroll=ft.ScrollMode.AUTO,
                    ),
                    ft.Row(
                        [self._retention_dropdown, self._prune_button],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        scroll=ft.ScrollMode.AUTO,
                    ),
                ],
                spacing=12,
            ),
            padding=16,
        )
        list_heading = ft.Row(
            [
                section_header(self._t("snapshots", "恢复点")),
                self._summary,
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self.controls = [
            self._page_header,
            create_panel,
            list_heading,
            self._backup_list,
        ]
        self._show_empty_state()

    def _build_backup_fields(self) -> None:
        """Create form controls used by the create/prune panels."""
        self._world_path_field = current_save_field(
            label=self._t("current_save", "当前存档"),
        )
        self._label_field = text_field(
            label=self._t("label", "备份备注"),
            hint_text=self._t("label_hint", "例如：升级前、安装模组前"),
        )
        self._create_button = btn_primary(
            self._t("create", "创建备份"),
            on_click=self._start_create,
            width=132,
            icon=IconSet.SAVE,
        )
        self._cancel_button = btn_danger(
            self._t("cancel", "取消操作"),
            on_click=self._cancel,
            width=120,
        )
        self._cancel_button.visible = False
        self._retention_dropdown = dropdown(
            label=self._t("retention", "保留最新恢复点"),
            options=[
                ft.dropdown.Option("3", "3"),
                ft.dropdown.Option("5", "5"),
                ft.dropdown.Option("10", "10"),
                ft.dropdown.Option("20", "20"),
            ],
            value="5",
            expand=False,
            width=180,
        )
        self._prune_button = ft.IconButton(
            icon=IconSet.CLEANUP,
            tooltip=self._t("prune", "清理旧恢复点"),
            icon_color=THEME.warning,
            on_click=self._confirm_prune,
        )
        self._summary = ft.Text(
            self._t("no_save", "尚未选择存档"),
            size=12,
            color=THEME.text_muted,
        )
        self._backup_list = ft.Column(spacing=10)

    def _selected_world(self) -> Path:
        value = str(self._world_path_field.value or "").strip()
        if not value:
            raise ValueError(self._t("select_valid_save", "请先选择有效存档"))
        # World validation (including level.dat I/O) belongs to BackupService's
        # worker operation; the Flet event handler only normalizes the value.
        return Path(value)

    def _current_world_path(self) -> Optional[Path]:
        """返回当前字段中的世界身份，空字段不触发用户提示。"""
        value = str(self._world_path_field.value or "").strip()
        return Path(value) if value else None

    def _refresh(self, event: Optional[ft.ControlEvent] = None) -> None:
        del event
        try:
            world = self._selected_world()
        except ValueError:
            self._summary.value = self._t("no_save", "尚未选择存档")
            self._show_empty_state()
            safe_update(self)
            return
        self._refresh_generation += 1
        generation = self._refresh_generation
        try:
            handle = self._task_scope.submit(
                "list_backups",
                lambda token: self.service.list_backups(world),
                lane=ExecutionLane.IO,
                priority=TaskPriority.VISIBLE,
            )
            handle.add_done_callback(
                lambda completed: self._finish_refresh(
                    completed,
                    world,
                    generation,
                )
            )
        except Exception as exc:
            self._post_to_ui(self._apply_refresh_failure, exc, generation)

    def _finish_refresh(
        self,
        handle: OperationHandle[list[BackupRecord]],
        world: Path,
        generation: int,
    ) -> None:
        if handle.cancelled:
            return
        try:
            records = handle.result()
        except (CancelledError, OperationCancelledError):
            return
        except Exception as exc:
            self._post_to_ui(self._apply_refresh_failure, exc, generation)
            return
        self._post_to_ui(
            self._apply_refresh_success,
            records,
            world,
            generation,
        )

    def _apply_refresh_success(
        self,
        records: list[BackupRecord],
        world: Path,
        generation: int,
    ) -> None:
        if generation != self._refresh_generation:
            return
        if str(self._world_path_field.value or "").strip() != str(world):
            return
        self._summary.value = self._t("count", "共 {count} 个恢复点").format(
            count=len(records)
        )
        if records:
            self._backup_list.controls = [self._backup_row(item) for item in records]
        else:
            self._show_empty_state()
        safe_update(self)

    def _apply_refresh_failure(self, error: Exception, generation: int) -> None:
        if generation != self._refresh_generation:
            return
        self._summary.value = self._t("load_failed", "备份列表加载失败")
        self._backup_list.controls = [
            placeholder(
                icon=IconSet.ERROR,
                title=self._t("load_failed", "备份列表加载失败"),
                subtitle=str(error),
                height=130,
            )
        ]
        safe_update(self)

    def _show_empty_state(self) -> None:
        self._backup_list.controls = [
            placeholder(
                icon=IconSet.HISTORY,
                title=self._t("empty", "暂无备份"),
                subtitle=self._t("empty_subtitle", "创建的恢复点会显示在这里"),
                height=140,
            )
        ]

    def _backup_row(self, record: BackupRecord) -> ft.Container:
        status_color = THEME.success if record.valid else THEME.error
        status_icon = IconSet.SUCCESS if record.valid else IconSet.ERROR
        description = ft.Column(
            self._backup_description_controls(record),
            spacing=3,
            expand=True,
        )
        actions = ft.Row(
            self._backup_action_buttons(record),
            spacing=2,
        )
        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(status_icon, size=24, color=status_color),
                    description,
                    actions,
                ],
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding(left=14, right=8, top=12, bottom=12),
            bgcolor=THEME.bg_card,
            border=mc_border(2),
            border_radius=8,
        )

    def _backup_description_controls(
        self,
        record: BackupRecord,
    ) -> list[ft.Control]:
        title = record.label or self._t("untitled", "未命名恢复点")
        created = record.created_at.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        details = self._t(
            "details",
            "{time} · {size} · {files} 个文件",
        ).format(
            time=created,
            size=format_size(record.size_bytes),
            files=record.file_count,
        )
        integrity = (
            self._t("integrity_ready", "可验证")
            if record.integrity_available
            else self._t("integrity_legacy", "旧版无清单")
        )
        controls: list[ft.Control] = [
            ft.Text(
                title,
                size=14,
                weight=ft.FontWeight.BOLD,
                color=THEME.text_primary,
            ),
            ft.Text(
                f"{details} · {integrity}",
                size=11,
                color=THEME.text_secondary,
            ),
        ]
        if not record.valid:
            controls.append(
                ft.Text(
                    record.validation_error,
                    size=11,
                    color=THEME.error,
                )
            )
        return controls

    def _backup_action_buttons(self, record: BackupRecord) -> list[ft.Control]:
        return [
            ft.IconButton(
                icon=IconSet.VERIFY,
                tooltip=self._t("verify", "验证完整性"),
                icon_color=THEME.mc_emerald,
                disabled=not record.valid or self._busy,
                on_click=lambda e, item=record: self._start_verify(item),
            ),
            ft.IconButton(
                icon=IconSet.RESTORE,
                tooltip=self._t("restore", "恢复此备份"),
                icon_color=THEME.mc_diamond,
                disabled=not record.valid or self._busy,
                on_click=lambda e, item=record: self._confirm_restore(item),
            ),
            ft.IconButton(
                icon=IconSet.DELETE,
                tooltip=self._t("delete", "删除此备份"),
                icon_color=THEME.error,
                disabled=self._busy,
                on_click=lambda e, item=record: self._confirm_delete(item),
            ),
        ]

    def _start_create(self, event: ft.ControlEvent) -> None:
        del event
        if self._busy:
            return
        try:
            world = self._selected_world()
        except ValueError as exc:
            self.app.warn_dialog(self._t("notice", "提示"), str(exc))
            return
        label = str(self._label_field.value or "")
        self._run_operation(
            world,
            self._t("creating", "正在创建备份..."),
            lambda token, progress: self.service.create_backup(
                world,
                label,
                progress,
                cancel_check=lambda: token.is_cancelled,
            ),
            self._t("create_success", "备份创建完成"),
            clear_label=True,
        )

    def _confirm_restore(self, record: BackupRecord) -> None:
        try:
            world = self._selected_world()
        except ValueError as exc:
            self.app.warn_dialog(self._t("notice", "提示"), str(exc))
            return
        message = self._t(
            "restore_confirm",
            "当前存档将被恢复点“{label}”完整替换。继续吗？",
        ).format(label=record.label or record.backup_id)
        self._show_confirmation(
            self._t("restore_title", "确认恢复"),
            message,
            self._t("restore", "恢复"),
            lambda: self._run_operation(
                world,
                self._t("restoring", "正在恢复备份..."),
                lambda token, progress: self.service.restore_backup(
                    world,
                    record.backup_id,
                    progress,
                    cancel_check=lambda: token.is_cancelled,
                ),
                self._t("restore_success", "备份恢复完成"),
            ),
        )

    def _confirm_delete(self, record: BackupRecord) -> None:
        try:
            world = self._selected_world()
        except ValueError as exc:
            self.app.warn_dialog(self._t("notice", "提示"), str(exc))
            return
        message = self._t(
            "delete_confirm",
            "恢复点“{label}”将被永久删除。继续吗？",
        ).format(label=record.label or record.backup_id)
        self._show_confirmation(
            self._t("delete_title", "确认删除"),
            message,
            self._t("delete", "删除"),
            lambda: self._run_operation(
                world,
                self._t("deleting", "正在删除备份..."),
                lambda token, progress: self._delete_record(
                    world,
                    record,
                    progress,
                    token,
                ),
                self._t("delete_success", "备份已删除"),
            ),
            destructive=True,
        )

    def _start_verify(self, record: BackupRecord) -> None:
        try:
            world = self._selected_world()
        except ValueError as exc:
            self.app.warn_dialog(self._t("notice", "提示"), str(exc))
            return

        def verify(
            token: CancellationToken,
            progress: Callable[[float, str], None],
        ) -> BackupVerification:
            result = self.service.verify_backup(
                world,
                record.backup_id,
                progress,
                cancel_check=lambda: token.is_cancelled,
            )
            if not result.valid:
                details = "; ".join(result.issues[:3])
                raise BackupError(f"备份完整性校验失败: {details}")
            return result

        self._run_operation(
            world,
            self._t("verifying", "正在验证备份..."),
            verify,
            self._verification_message,
        )

    def _confirm_prune(self) -> None:
        try:
            world = self._selected_world()
            keep_latest = int(self._retention_dropdown.value or "5")
        except (ValueError, TypeError) as exc:
            self.app.warn_dialog(self._t("notice", "提示"), str(exc))
            return
        message = self._t(
            "prune_confirm",
            "将永久删除除最新 {count} 个之外的恢复点。继续吗？",
        ).format(count=keep_latest)
        self._show_confirmation(
            self._t("prune_title", "确认清理"),
            message,
            self._t("prune", "清理"),
            lambda: self._run_operation(
                world,
                self._t("pruning", "正在清理旧恢复点..."),
                lambda token, progress: self._prune_records(
                    world,
                    keep_latest,
                    progress,
                    token,
                ),
                self._prune_message,
            ),
            destructive=True,
        )

    def _prune_records(
        self,
        world: Path,
        keep_latest: int,
        progress: Callable[[float, str], None],
        token: CancellationToken,
    ) -> object:
        progress(0.1, self._t("pruning", "正在清理旧恢复点..."))
        removed = self.service.prune_backups(
            world,
            keep_latest,
            cancel_check=lambda: token.is_cancelled,
        )
        progress(1.0, self._t("prune_success", "旧恢复点清理完成"))
        return removed

    def _verification_message(self, value: object) -> str:
        if not isinstance(value, BackupVerification):
            return self._t("verify_success", "备份完整性校验通过")
        if not value.complete:
            return self._t("verify_legacy", "旧版备份没有完整性清单")
        return self._t(
            "verify_details",
            "校验通过：{files} 个文件，{size}",
        ).format(
            files=value.checked_files,
            size=format_size(value.checked_bytes),
        )

    def _prune_message(self, value: object) -> str:
        count = len(value) if isinstance(value, list) else 0
        return self._t(
            "prune_details",
            "已清理 {count} 个旧恢复点",
        ).format(count=count)

    def _delete_record(
        self,
        world: Path,
        record: BackupRecord,
        progress: Callable[[float, str], None],
        token: CancellationToken,
    ) -> None:
        progress(0.2, self._t("deleting", "正在删除备份..."))
        self.service.delete_backup(
            world,
            record.backup_id,
            cancel_check=lambda: token.is_cancelled,
        )
        progress(1.0, self._t("delete_success", "备份已删除"))

    def _show_confirmation(
        self,
        title: str,
        message: str,
        action_label: str,
        action: Callable[[], None],
        destructive: bool = False,
    ) -> None:
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(title, color=THEME.text_primary),
            content=ft.Text(message, color=THEME.text_secondary),
            actions=[],
        )

        def close() -> None:
            dialog.open = False
            self.app.page.update()

        def confirm() -> None:
            close()
            action()

        action_color = THEME.error if destructive else THEME.mc_diamond
        actions: list[ft.Control] = [
            ft.TextButton(
                action_label,
                style=ft.ButtonStyle(color=action_color),
                on_click=confirm,
            ),
            ft.TextButton(self._t("cancel", "取消"), on_click=close),
        ]
        dialog.actions = actions
        self.app.page.show_dialog(dialog)

    def _run_operation(
        self,
        world: Path,
        task_name: str,
        operation: Callable[
            [CancellationToken, Callable[[float, str], None]],
            object,
        ],
        success_message: str | Callable[[object], str],
        clear_label: bool = False,
    ) -> None:
        if self._busy:
            return
        try:
            self._operation_controller.start(
                BackupOperationRequest(
                    world_path=world,
                    task_name=task_name,
                    operation=operation,
                    on_success=lambda result: self._finish_success(
                        success_message,
                        result,
                        clear_label,
                    ),
                    on_error=self._finish_error,
                )
            )
        except BackupOperationBusyError:
            return
        except Exception as exc:
            self._finish_error(exc)

    def _finish_success(
        self,
        message: str | Callable[[object], str],
        result: object,
        clear_label: bool,
    ) -> None:
        if clear_label:
            self._label_field.value = ""
        self._refresh()
        resolved_message = message(result) if callable(message) else message
        self.app.info_dialog(self._t("completed", "完成"), resolved_message)

    def _finish_error(self, error: Exception) -> None:
        self.app.handle_exception(error, title=self._t("operation_failed", "备份操作失败"))

    def _post_to_ui(self, callback: Callable[..., object], *args: object) -> None:
        """投递 UI 回调；无页面测试环境直接执行。"""
        page = getattr(self.app, "page", None)
        if page is None:
            callback(*args)
            return
        run_on_ui(page, callback, *args)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._create_button.disabled = busy
        self._prune_button.disabled = busy
        self._retention_dropdown.disabled = busy
        self._cancel_button.visible = busy
        self._cancel_button.disabled = not busy
        safe_update(self)

    def _set_cancel_pending(self) -> None:
        """取消请求发出后禁用按钮，等待安全检查点确认。"""
        self._cancel_button.disabled = True
        safe_update(self._cancel_button)

    def _cancel(self, event: ft.ControlEvent) -> None:
        del event
        self._operation_controller.cancel()

    def on_save_selected(self, path: str) -> None:
        """响应侧边栏「当前存档」变更并刷新备份列表。

        Args:
            path: 新选中的世界目录路径。
        """
        self._task_scope.cancel_all()
        self._operation_controller.invalidate()
        self._refresh_generation += 1
        self._world_path_field.value = path
        self._refresh()

    def dispose(self) -> None:
        """取消备份操作并释放页面任务作用域。"""
        self._operation_controller.close()
        self._refresh_generation += 1
        self._task_scope.close()
