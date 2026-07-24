"""Save Repair View - 存档修复视图

支持存档检测（只读诊断）和存档修复（修改文件）。
"""
from pathlib import Path
from typing import Protocol

import flet as ft

from app.controllers.save_repair_controller import (
    RepairOptions,
    SaveRepairController,
    SaveRepairUiPorts,
)
from app.presenters.save_repair_presenter import (
    format_detect_report,
    format_repair_report,
)
from app.services.save_repair_service import (
    DetectReport,
    RepairReport,
    SaveRepairService,
)
from app.ui.feature_context import (
    FeatureDialogPort,
    FeaturePagePort,
    FeatureProgressPort,
    FeatureRuntimePort,
)
from app.ui.theme import THEME
from app.ui.utils import run_on_ui, safe_update
from app.ui.view_actions import ViewAction
from app.ui.views.save_repair_chrome import build_save_repair_chrome


class SaveRepairHost(
    FeaturePagePort,
    FeatureDialogPort,
    FeatureProgressPort,
    FeatureRuntimePort,
    Protocol,
):
    """Ports required by the save repair view."""

    @property
    def save_repair(self) -> SaveRepairService:
        """Return the shared save repair service."""
        ...


class SaveRepairView(ft.Column):
    """存档修复视图"""

    def __init__(
        self,
        app: "SaveRepairHost",
        service: SaveRepairService | None = None,
    ) -> None:
        """初始化存档修复视图。

        Args:
            app: 修复页面所需的 UI、运行时和修复服务端口。
            service: 可选修复服务；缺省使用上下文的修复端口。
        """
        super().__init__(spacing=20, scroll=ft.ScrollMode.AUTO)
        self.app = app
        self.service = service or app.save_repair
        self._task_scope = app.execution_runtime.create_scope(
            "save_repair_view"
        )
        self.expand = True
        self._busy = False
        self._build_ui()
        self._controller = SaveRepairController(
            self.service,
            self._task_scope,
            SaveRepairUiPorts(
                show_progress=self.app.show_progress,
                update_progress=self.app.update_progress_with_task,
                append_log=self._append_log,
                show_detect_report=self._show_detect_report,
                show_repair_report=self._show_repair_report,
                show_detect_error=self._show_detect_error,
                show_repair_error=self._show_repair_error,
                finish_operation=self._finish_operation,
            ),
            post_ui=lambda callback: run_on_ui(self.app.page, callback),
        )

    def get_top_actions(self) -> list[ViewAction]:
        """Keep detect/repair commands beside their configuration form."""
        return []

    def _build_ui(self) -> None:
        chrome = build_save_repair_chrome(
            on_detect=self._start_detect,
            on_repair=self._start_repair,
            on_cancel=self._cancel,
        )
        self._page_header = chrome.page_header
        self._world_path_field = chrome.world_path_field
        self._fix_chunks_checkbox = chrome.fix_chunks_checkbox
        self._fix_players_checkbox = chrome.fix_players_checkbox
        self._fix_level_dat_checkbox = chrome.fix_level_dat_checkbox
        self._backup_checkbox = chrome.backup_checkbox
        self._log_column = chrome.log_column
        self._world_info_text = chrome.world_info_text
        self._world_info_card = chrome.world_info_card
        self._detect_result_text = chrome.detect_result_text
        self._detect_result_card = chrome.detect_result_card
        self._result_text = chrome.result_text
        self._detect_btn = chrome.detect_button
        self._repair_btn = chrome.repair_button
        self._cancel_btn = chrome.cancel_button
        self.controls = chrome.controls

    # ── 事件处理 ──────────────────────────────────────────

    def _validate_path(self) -> Path:
        world_path = self._world_path_field.value
        if not world_path:
            raise ValueError("请先通过侧边栏设置当前存档目录")
        return Path(world_path)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._detect_btn.disabled = busy
        self._repair_btn.disabled = busy
        self._cancel_btn.visible = busy
        self._cancel_btn.disabled = False
        safe_update(self._detect_btn)
        safe_update(self._repair_btn)
        safe_update(self._cancel_btn)

    def _start_detect(self, e: ft.ControlEvent) -> None:
        if self._busy:
            self.app.warn_dialog("提示", "操作正在进行中，请稍候")
            return
        try:
            world_path = self._validate_path()
        except ValueError as ex:
            self.app.warn_dialog("提示", str(ex))
            return

        self._set_busy(True)
        self._log_column.controls.clear()
        safe_update(self._log_column)
        self._detect_result_card.visible = False
        safe_update(self._detect_result_card)
        self._world_info_card.visible = False
        safe_update(self._world_info_card)

        try:
            self._controller.start_detect(world_path)
        except Exception as exc:
            self._set_busy(False)
            self.app.handle_exception(exc, title="启动存档检测失败")

    def _start_repair(self, e: ft.ControlEvent) -> None:
        if self._busy:
            self.app.warn_dialog("提示", "操作正在进行中，请稍候")
            return
        try:
            world_path = self._validate_path()
        except ValueError as ex:
            self.app.warn_dialog("提示", str(ex))
            return

        self._set_busy(True)
        self._result_text.value = ""
        safe_update(self._result_text)
        self._log_column.controls.clear()
        safe_update(self._log_column)

        options = RepairOptions(
            fix_chunks=bool(self._fix_chunks_checkbox.value),
            fix_players=bool(self._fix_players_checkbox.value),
            fix_level_dat=bool(self._fix_level_dat_checkbox.value),
            backup=bool(self._backup_checkbox.value),
        )
        try:
            self._controller.start_repair(world_path, options)
        except Exception as exc:
            self._set_busy(False)
            self.app.handle_exception(exc, title="启动存档修复失败")

    def _cancel(self, e: ft.ControlEvent) -> None:
        del e
        self._controller.cancel()
        self._cancel_btn.disabled = True
        safe_update(self._cancel_btn)

    def _finish_operation(self) -> None:
        """恢复由当前后台任务占用的 UI。"""
        self.app.hide_progress()
        self._set_busy(False)

    def _show_detect_error(self, error: Exception) -> None:
        self._detect_result_text.value = f"检测失败: {error}"
        safe_update(self._detect_result_text)
        self._detect_result_card.visible = True
        safe_update(self._detect_result_card)
        self.app.error_dialog("错误", f"检测失败: {error}")

    def _show_detect_report(self, report: DetectReport) -> None:
        text = format_detect_report(report)
        self._world_info_text.value = text.world_info
        safe_update(self._world_info_text)
        self._world_info_card.visible = True
        safe_update(self._world_info_card)
        self._detect_result_text.value = text.result
        safe_update(self._detect_result_text)
        self._detect_result_card.visible = True
        safe_update(self._detect_result_card)

    def _show_repair_error(self, error: Exception) -> None:
        self._result_text.value = f"修复失败: {error}"
        safe_update(self._result_text)
        self.app.error_dialog("错误", f"修复失败: {error}")

    # ── 结果展示 ──────────────────────────────────────────

    def _show_repair_report(self, report: RepairReport) -> None:
        self._result_text.value = format_repair_report(report)
        safe_update(self._result_text)
        if report.success:
            self.app.info_dialog("完成", "存档修复完成！")
        elif not report.cancelled:
            self.app.error_dialog("修复失败", "修复未完成，存档未进入后续修复步骤。")

    def _append_log(self, msg: str, level: str) -> None:
        color_map = {
            "INFO": THEME.text_secondary,
            "WARNING": THEME.warning,
            "ERROR": THEME.error,
            "SUCCESS": THEME.success,
        }
        color = color_map.get(level.upper(), THEME.text_secondary)
        prefix_map = {
            "INFO": "[INFO]",
            "WARNING": "[WARN]",
            "ERROR": "[ERR]",
            "SUCCESS": "[OK]",
        }
        prefix = prefix_map.get(level.upper(), "[INFO]")

        log_entry = ft.Text(
            f"{prefix} {msg}",
            size=11,
            color=color,
            selectable=True,
            font_family="monospace",
        )
        self._log_column.controls.append(log_entry)
        safe_update(self._log_column)

    def on_save_selected(self, path: str) -> None:
        """统一入口设置当前存档回调"""
        self._controller.select_world(path)
        try:
            self._world_path_field.value = path
            # 隐藏之前的结果
            self._world_info_card.visible = False
            self._detect_result_card.visible = False
        except Exception:
            # UI best-effort: fields may be unmounted during teardown.
            pass
        safe_update(self._world_path_field)
        safe_update(self._world_info_card)
        safe_update(self._detect_result_card)

    def dispose(self) -> None:
        """取消检测/修复任务并释放页面作用域。"""
        self._controller.close()
        self._task_scope.close()
