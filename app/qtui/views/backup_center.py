"""备份与恢复中心（Qt 版，对应 Flet 树同名视图）。

创建、检查、恢复和删除受管世界快照。
领域逻辑复用 ``app.controllers.backup_operation_controller`` 与
``app.services.backup_service``。
"""
from __future__ import annotations

from concurrent.futures import CancelledError
from functools import partial
from pathlib import Path
from typing import Callable, Optional, Protocol

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.controllers.backup_operation_controller import (
    BackupOperationBusyError,
    BackupOperationController,
    BackupOperationRequest,
    BackupOperationUiPorts,
)
from app.qtui.components.buttons import btn_danger, btn_primary
from app.qtui.components.cards import card, section_title
from app.qtui.components.fields import dropdown, text_field
from app.qtui.components.layout import page_header
from app.qtui.context import (
    QtDialogPort,
    QtProgressPort,
    QtRuntimePort,
    QtTranslationPort,
)
from app.qtui.theme import get_theme_manager
from app.qtui.utils import format_size, run_on_ui
from app.qtui.view_actions import QtViewAction
from app.services.backup_service import (
    BackupError,
    BackupRecord,
    BackupService,
    BackupVerification,
)
from app.services.execution_runtime import (
    CancellationToken,
    ExecutionLane,
    OperationCancelledError,
    OperationHandle,
    TaskPriority,
)


class BackupHost(
    QtTranslationPort,
    QtDialogPort,
    QtProgressPort,
    QtRuntimePort,
    Protocol,
):
    """备份页面所需的端口。"""

    @property
    def backup(self) -> BackupService:
        """返回共享备份服务。"""
        ...


class BackupCenterView(QScrollArea):
    """创建、检查、恢复和删除受管世界快照。"""

    def __init__(
        self,
        app: BackupHost,
        service: Optional[BackupService] = None,
    ) -> None:
        """初始化备份中心视图。

        Args:
            app: 备份页面所需的 UI、运行时和备份服务端口。
            service: 可选备份服务；缺省使用上下文的备份端口。
        """
        super().__init__()
        self.app = app
        self.service = service or app.backup
        self._task_scope = app.execution_runtime.create_scope("backup_center_view")
        self._busy = False
        self._refresh_generation = 0

        self.setWidgetResizable(True)
        self._build_ui()
        self._operation_controller = BackupOperationController(
            self._task_scope,
            BackupOperationUiPorts(
                dispatch=lambda callback: run_on_ui(callback),
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

    def get_top_actions(self) -> list[QtViewAction]:
        """创建入口已置于表单区，顶栏无额外命令。"""
        return []

    def _build_ui(self) -> None:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)

        # ─── 页头 + 刷新按钮 ──────────────────────
        header_row = QWidget()
        header_layout = QHBoxLayout(header_row)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        header_layout.addWidget(page_header(
            self._t("title", "备份与恢复"),
            self._t("subtitle", "管理完整世界快照和恢复点"),
            icon="🕐",
        ))
        refresh_button = QPushButton("🔄")
        refresh_button.setFixedWidth(36)
        refresh_button.setToolTip(self._t("refresh", "刷新备份列表"))
        refresh_button.clicked.connect(lambda: self._refresh())
        header_layout.addWidget(
            refresh_button,
            alignment=Qt.AlignmentFlag.AlignTop,
        )
        layout.addWidget(header_row)

        # ─── 创建面板 ─────────────────────────────
        create_body = QWidget()
        create_layout = QVBoxLayout(create_body)
        create_layout.setContentsMargins(0, 0, 0, 0)
        create_layout.setSpacing(12)

        self._world_path_field = QLineEdit()
        self._world_path_field.setPlaceholderText(
            self._t("current_save", "当前存档")
        )
        create_layout.addWidget(self._world_path_field)

        self._label_field = text_field(
            hint_text=self._t("label_hint", "例如：升级前、安装模组前"),
        )
        self._label_field.setPlaceholderText(self._t("label", "备份备注"))
        create_layout.addWidget(self._label_field)

        buttons_row = QWidget()
        buttons_layout = QHBoxLayout(buttons_row)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(10)
        self._create_button = btn_primary(
            f"💾 {self._t('create', '创建备份')}",
            width=132,
            on_click=self._start_create,
        )
        self._cancel_button = btn_danger(
            self._t("cancel", "取消操作"),
            width=120,
            on_click=self._cancel,
        )
        self._cancel_button.setVisible(False)
        buttons_layout.addWidget(self._create_button)
        buttons_layout.addWidget(self._cancel_button)
        buttons_layout.addStretch(1)
        create_layout.addWidget(buttons_row)

        retention_row = QWidget()
        retention_layout = QHBoxLayout(retention_row)
        retention_layout.setContentsMargins(0, 0, 0, 0)
        retention_layout.setSpacing(8)
        retention_layout.addWidget(QLabel(self._t("retention", "保留最新恢复点")))
        self._retention_dropdown = dropdown(
            options=["3", "5", "10", "20"],
            value="5",
            width=180,
        )
        retention_layout.addWidget(self._retention_dropdown)
        prune_button = QPushButton(f"🧹 {self._t('prune', '清理旧恢复点')}")
        prune_button.setToolTip(self._t("prune", "清理旧恢复点"))
        prune_button.clicked.connect(lambda: self._confirm_prune())
        retention_layout.addWidget(prune_button)
        retention_layout.addStretch(1)
        create_layout.addWidget(retention_row)

        layout.addWidget(card(create_body, padding=16))

        # ─── 恢复点列表 ───────────────────────────
        list_heading = QWidget()
        heading_layout = QHBoxLayout(list_heading)
        heading_layout.setContentsMargins(0, 0, 0, 0)
        heading_layout.setSpacing(8)
        heading_layout.addWidget(section_title(self._t("snapshots", "恢复点")))
        heading_layout.addStretch(1)
        self._summary = QLabel(self._t("no_save", "尚未选择存档"))
        self._summary.setProperty("role", "muted")
        heading_layout.addWidget(self._summary)
        layout.addWidget(list_heading)

        self._backup_list_layout = QVBoxLayout()
        self._backup_list_layout.setSpacing(10)
        layout.addLayout(self._backup_list_layout)

        layout.addStretch(1)
        self.setWidget(content)
        self._show_empty_state()

    # ─── 状态辅助 ─────────────────────────────────

    def _selected_world(self) -> Path:
        value = self._world_path_field.text().strip()
        if not value:
            raise ValueError(self._t("select_valid_save", "请先选择有效存档"))
        return Path(value)

    def _current_world_path(self) -> Optional[Path]:
        """返回字段中的世界身份，空字段不触发用户提示。"""
        value = self._world_path_field.text().strip()
        return Path(value) if value else None

    # ─── 列表刷新 ─────────────────────────────────

    def _refresh(self) -> None:
        try:
            world = self._selected_world()
        except ValueError:
            self._summary.setText(self._t("no_save", "尚未选择存档"))
            self._show_empty_state()
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
            run_on_ui(self._apply_refresh_failure, exc, generation)

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
            run_on_ui(self._apply_refresh_failure, exc, generation)
            return
        run_on_ui(self._apply_refresh_success, records, world, generation)

    def _apply_refresh_success(
        self,
        records: list[BackupRecord],
        world: Path,
        generation: int,
    ) -> None:
        if generation != self._refresh_generation:
            return
        if self._world_path_field.text().strip() != str(world):
            return
        self._summary.setText(
            self._t("count", "共 {count} 个恢复点").format(count=len(records))
        )
        if records:
            self._rebuild_backup_list(
                [self._backup_row(record) for record in records]
            )
        else:
            self._show_empty_state()

    def _apply_refresh_failure(self, error: Exception, generation: int) -> None:
        if generation != self._refresh_generation:
            return
        self._summary.setText(self._t("load_failed", "备份列表加载失败"))
        label = QLabel(
            f"{self._t('load_failed', '备份列表加载失败')}\n{error}"
        )
        label.setProperty("role", "muted")
        self._rebuild_backup_list([label])

    def _show_empty_state(self) -> None:
        empty = QLabel(
            f"🕐 {self._t('empty', '暂无备份')}\n"
            f"{self._t('empty_subtitle', '创建的恢复点会显示在这里')}"
        )
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.setProperty("role", "muted")
        self._rebuild_backup_list([empty])

    def _rebuild_backup_list(self, widgets: list[QWidget]) -> None:
        """重建备份列表（幂等）。"""
        while self._backup_list_layout.count():
            item = self._backup_list_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for widget in widgets:
            self._backup_list_layout.addWidget(widget)
        self._backup_list_layout.addStretch(1)

    # ─── 列表行 ───────────────────────────────────

    def _backup_row(self, record: BackupRecord) -> QWidget:
        theme = get_theme_manager().current
        status = ("✅", theme.success) if record.valid else ("⛔", theme.error)

        description = QWidget()
        description_layout = QVBoxLayout(description)
        description_layout.setContentsMargins(0, 0, 0, 0)
        description_layout.setSpacing(3)

        title = QLabel(record.label or self._t("untitled", "未命名恢复点"))
        title.setStyleSheet("font-size: 14px; font-weight: 600;")
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
        details_label = QLabel(f"{details} · {integrity}")
        details_label.setStyleSheet(f"font-size: 11px; color: {theme.text_secondary};")
        description_layout.addWidget(title)
        description_layout.addWidget(details_label)
        if not record.valid:
            error_label = QLabel(record.validation_error)
            error_label.setStyleSheet(f"font-size: 11px; color: {theme.error};")
            description_layout.addWidget(error_label)

        actions = QWidget()
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(4)
        for glyph_text, tooltip, callback, enabled in self._backup_action_specs(record):
            button = QPushButton(glyph_text)
            button.setFixedWidth(34)
            button.setToolTip(tooltip)
            button.setEnabled(enabled)
            button.clicked.connect(lambda _checked, cb=callback: cb())
            actions_layout.addWidget(button)

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(14, 12, 8, 12)
        row_layout.setSpacing(12)
        status_label = QLabel(status[0])
        status_label.setStyleSheet(f"font-size: 20px; color: {status[1]};")
        row_layout.addWidget(status_label)
        row_layout.addWidget(description, 1)
        row_layout.addWidget(actions)

        frame = QWidget()
        frame.setProperty("role", "card")
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.addWidget(row)
        return frame

    def _backup_action_specs(
        self,
        record: BackupRecord,
    ) -> list[tuple[str, str, Callable[[], None], bool]]:
        return [
            (
                "✅",
                self._t("verify", "验证完整性"),
                partial(self._start_verify, record),
                record.valid and not self._busy,
            ),
            (
                "♻️",
                self._t("restore", "恢复此备份"),
                partial(self._confirm_restore, record),
                record.valid and not self._busy,
            ),
            (
                "🗑️",
                self._t("delete", "删除此备份"),
                partial(self._confirm_delete, record),
                not self._busy,
            ),
        ]

    # ─── 操作入口 ─────────────────────────────────

    def _start_create(self) -> None:
        if self._busy:
            return
        try:
            world = self._selected_world()
        except ValueError as exc:
            self.app.warn_dialog(self._t("notice", "提示"), str(exc))
            return
        label = self._label_field.text()
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
            keep_latest = int(self._retention_dropdown.currentText() or "5")
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
        box = QMessageBox(self)
        box.setIcon(
            QMessageBox.Icon.Warning if destructive else QMessageBox.Icon.Question
        )
        box.setWindowTitle(title)
        box.setText(message)
        confirm_button = box.addButton(action_label, QMessageBox.ButtonRole.AcceptRole)
        box.addButton(self._t("cancel", "取消"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is confirm_button:
            action()

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
            self._label_field.clear()
        self._refresh()
        resolved_message = message(result) if callable(message) else message
        self.app.info_dialog(self._t("completed", "完成"), resolved_message)

    def _finish_error(self, error: Exception) -> None:
        self.app.handle_exception(
            error,
            title=self._t("operation_failed", "备份操作失败"),
        )

    # ─── 忙碌状态 ─────────────────────────────────

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._create_button.setEnabled(not busy)
        self._retention_dropdown.setEnabled(not busy)
        self._cancel_button.setVisible(busy)
        self._cancel_button.setEnabled(busy)

    def _set_cancel_pending(self) -> None:
        """取消请求发出后禁用按钮，等待安全检查点确认。"""
        self._cancel_button.setEnabled(False)

    def _cancel(self) -> None:
        self._operation_controller.cancel()

    # ─── 存档选择回调 ─────────────────────────────

    def on_save_selected(self, path: str) -> None:
        """响应侧边栏「当前存档」变更并刷新备份列表。"""
        self._task_scope.cancel_all()
        self._operation_controller.invalidate()
        self._refresh_generation += 1
        self._world_path_field.setText(path)
        self._refresh()

    def on_save_cleared(self) -> None:
        """取消旧世界操作并清空备份列表投影。"""
        self._task_scope.cancel_all()
        self._operation_controller.invalidate()
        self._refresh_generation += 1
        self._world_path_field.clear()
        self._summary.setText(self._t("no_save", "尚未选择存档"))
        self._show_empty_state()

    def dispose(self) -> None:
        """取消备份操作并释放页面任务作用域。"""
        self._operation_controller.close()
        self._refresh_generation += 1
        self._task_scope.close()
