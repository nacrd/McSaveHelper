"""存档修复视图（Qt 版，对应 Flet 树同名视图）。

支持存档检测（只读诊断）和存档修复（修改文件）。
领域逻辑复用 ``app.controllers.save_repair_controller`` 与
``app.presenters.save_repair_presenter``。
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.controllers.save_repair_controller import (
    RepairOptions,
    SaveRepairController,
    SaveRepairUiPorts,
)
from app.presenters.save_repair_presenter import (
    format_detect_report,
    format_repair_report,
)
from app.qtui.components.buttons import btn_ghost, btn_primary
from app.qtui.components.cards import card, section_title
from app.qtui.components.layout import page_header
from app.qtui.context import (
    QtDialogPort,
    QtProgressPort,
    QtRuntimePort,
    QtTranslationPort,
)
from app.qtui.icons import glyph
from app.qtui.theme import get_theme_manager
from app.qtui.utils import run_on_ui
from app.qtui.view_actions import QtViewAction
from app.services.save_repair.models import DetectReport, RepairReport
from app.services.save_repair_service import SaveRepairService

_LOG_COLORS = {
    "INFO": "text_secondary",
    "WARNING": "warning",
    "ERROR": "error",
    "SUCCESS": "success",
}
_LOG_PREFIXES = {
    "INFO": "[INFO]",
    "WARNING": "[WARN]",
    "ERROR": "[ERR]",
    "SUCCESS": "[OK]",
}


class SaveRepairHost(
    QtTranslationPort,
    QtDialogPort,
    QtProgressPort,
    QtRuntimePort,
    Protocol,
):
    """修复页面所需的 UI、运行时与修复服务端口。"""

    @property
    def save_repair(self) -> SaveRepairService:
        """返回共享存档修复服务。"""
        ...


class SaveRepairView(QScrollArea):
    """存档修复视图"""

    def __init__(
        self,
        app: SaveRepairHost,
        service: SaveRepairService | None = None,
    ) -> None:
        """初始化存档修复视图。

        Args:
            app: 修复页面所需的 UI、运行时和修复服务端口。
            service: 可选修复服务；缺省使用上下文的修复端口。
        """
        super().__init__()
        self.app = app
        self.service = service or app.save_repair
        self._task_scope = app.execution_runtime.create_scope("save_repair_view")
        self._busy = False
        self._has_detect_report = False

        self.setWidgetResizable(True)
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
            post_ui=lambda callback: run_on_ui(callback),
        )

    def get_top_actions(self) -> list[QtViewAction]:
        """检测/修复命令已置于表单区，顶栏无额外命令。"""
        return []

    def _build_ui(self) -> None:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        layout.addWidget(page_header(
            "存档修复",
            "检测存档状态、修复损坏的区块、玩家数据、level.dat",
            icon=glyph("BUILD"),
        ))

        # ─── 配置卡片 ─────────────────────────────
        config_body = QWidget()
        config_layout = QVBoxLayout(config_body)
        config_layout.setContentsMargins(0, 0, 0, 0)
        config_layout.setSpacing(10)

        config_layout.addWidget(section_title("当前存档"))
        self._world_path_field = QLineEdit()
        self._world_path_field.setPlaceholderText(
            "请通过侧边栏「设置当前存档」设置要修复的当前存档目录"
        )
        config_layout.addWidget(self._world_path_field)

        config_layout.addWidget(section_title("操作"))
        actions_row = QWidget()
        actions_layout = QHBoxLayout(actions_row)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(12)
        self._detect_button = btn_primary("检测存档", on_click=self._start_detect)
        self._repair_button = btn_primary("开始修复", on_click=self._start_repair)
        self._repair_button.setEnabled(False)
        self._cancel_button = btn_ghost("取消", on_click=self._cancel)
        self._cancel_button.setVisible(False)
        actions_layout.addWidget(self._detect_button)
        actions_layout.addWidget(self._repair_button)
        actions_layout.addWidget(self._cancel_button)
        actions_layout.addStretch(1)
        config_layout.addWidget(actions_row)

        config_layout.addWidget(section_title("修复选项"))
        self._fix_chunks_checkbox = QCheckBox("修复区块")
        self._fix_chunks_checkbox.setChecked(True)
        self._fix_players_checkbox = QCheckBox("修复玩家数据")
        self._fix_players_checkbox.setChecked(True)
        self._fix_level_dat_checkbox = QCheckBox("修复 level.dat")
        self._fix_level_dat_checkbox.setChecked(True)
        self._backup_checkbox = QCheckBox("创建备份（推荐）")
        self._backup_checkbox.setChecked(True)
        options_column = QWidget()
        options_layout = QVBoxLayout(options_column)
        options_layout.setContentsMargins(0, 0, 0, 0)
        options_layout.setSpacing(6)
        options_layout.addWidget(self._fix_chunks_checkbox)
        options_layout.addWidget(self._fix_players_checkbox)
        options_layout.addWidget(self._fix_level_dat_checkbox)
        options_layout.addWidget(self._backup_checkbox)
        self._repair_options = options_column
        self._repair_options.setEnabled(False)
        config_layout.addWidget(options_column)

        layout.addWidget(card(config_body, padding=16))

        # ─── 世界信息卡片（默认隐藏） ───────────────
        self._world_info_text = self._result_label()
        self._world_info_card = self._result_card("世界信息", self._world_info_text)
        self._world_info_card.setVisible(False)
        layout.addWidget(self._world_info_card)

        # ─── 检测结果卡片（默认隐藏） ───────────────
        self._detect_result_text = self._result_label()
        self._detect_result_card = self._result_card(
            "检测结果", self._detect_result_text
        )
        self._detect_result_card.setVisible(False)
        layout.addWidget(self._detect_result_card)

        # ─── 修复结果卡片 ─────────────────────────
        self._result_text = self._result_label()
        self._repair_result_card = self._result_card(
            "修复结果", self._result_text
        )
        self._repair_result_card.setVisible(False)
        layout.addWidget(self._repair_result_card)

        # ─── 执行日志卡片 ─────────────────────────
        log_body = QWidget()
        log_layout = QVBoxLayout(log_body)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(10)
        log_layout.addWidget(section_title("执行日志"))
        self._log_view = QTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMinimumHeight(180)
        self._log_view.setFontFamily("Consolas")
        log_layout.addWidget(self._log_view)
        self._log_card = card(log_body, padding=16)
        self._log_card.setVisible(False)
        layout.addWidget(self._log_card)

        layout.addStretch(1)
        self.setWidget(content)

    # ── 构建辅助 ──────────────────────────────────

    @staticmethod
    def _result_label() -> QLabel:
        label = QLabel("")
        label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        label.setWordWrap(True)
        return label

    @staticmethod
    def _result_card(title: str, text: QLabel) -> QWidget:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(section_title(title))
        layout.addWidget(text)
        return card(body, padding=16)

    # ── 事件处理 ──────────────────────────────────

    def _validate_path(self) -> Path:
        world_path = self._world_path_field.text().strip()
        if not world_path:
            raise ValueError("请先通过侧边栏设置当前存档目录")
        return Path(world_path)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._detect_button.setEnabled(not busy)
        self._repair_button.setEnabled(not busy and self._has_detect_report)
        self._cancel_button.setVisible(busy)
        self._cancel_button.setEnabled(True)

    def _start_detect(self) -> None:
        if self._busy:
            self.app.warn_dialog("提示", "操作正在进行中，请稍候")
            return
        try:
            world_path = self._validate_path()
        except ValueError as exc:
            self.app.warn_dialog("提示", str(exc))
            return

        self._set_busy(True)
        self._reset_detected_state()
        self._log_view.clear()
        self._log_card.setVisible(True)
        self._world_info_card.setVisible(False)
        self._detect_result_card.setVisible(False)

        try:
            self._controller.start_detect(world_path)
        except Exception as exc:
            self._set_busy(False)
            self.app.handle_exception(exc, title="启动存档检测失败")

    def _start_repair(self) -> None:
        if self._busy:
            self.app.warn_dialog("提示", "操作正在进行中，请稍候")
            return
        if not self._has_detect_report:
            self.app.warn_dialog("提示", "请先检测当前存档，再选择修复项。")
            return
        try:
            world_path = self._validate_path()
        except ValueError as exc:
            self.app.warn_dialog("提示", str(exc))
            return

        self._set_busy(True)
        self._result_text.setText("")
        self._repair_result_card.setVisible(False)
        self._log_view.clear()
        self._log_card.setVisible(True)

        options = RepairOptions(
            fix_chunks=bool(self._fix_chunks_checkbox.isChecked()),
            fix_players=bool(self._fix_players_checkbox.isChecked()),
            fix_level_dat=bool(self._fix_level_dat_checkbox.isChecked()),
            backup=bool(self._backup_checkbox.isChecked()),
        )
        try:
            self._controller.start_repair(world_path, options)
        except Exception as exc:
            self._set_busy(False)
            self.app.handle_exception(exc, title="启动存档修复失败")

    def _cancel(self) -> None:
        self._controller.cancel()
        self._cancel_button.setEnabled(False)

    def _finish_operation(self) -> None:
        """恢复由当前后台任务占用的 UI。"""
        self.app.hide_progress()
        self._set_busy(False)

    def _show_detect_error(self, error: Exception) -> None:
        self._reset_detected_state()
        self._detect_result_text.setText(f"检测失败: {error}")
        self._detect_result_card.setVisible(True)
        self.app.error_dialog("错误", f"检测失败: {error}")

    def _show_detect_report(self, report: DetectReport) -> None:
        text = format_detect_report(report)
        self._world_info_text.setText(text.world_info)
        self._world_info_card.setVisible(True)
        self._detect_result_text.setText(text.result)
        self._detect_result_card.setVisible(True)
        self._apply_detected_options(report)

    def _show_repair_error(self, error: Exception) -> None:
        self._result_text.setText(f"修复失败: {error}")
        self._repair_result_card.setVisible(True)
        self.app.error_dialog("错误", f"修复失败: {error}")

    def _show_repair_report(self, report: RepairReport) -> None:
        self._result_text.setText(format_repair_report(report))
        self._repair_result_card.setVisible(True)
        if report.success:
            self._reset_detected_state()
            self.app.info_dialog("完成", "存档修复完成！")
        elif not report.cancelled:
            self.app.error_dialog("修复失败", "修复未完成，存档未进入后续修复步骤。")

    def _append_log(self, msg: str, level: str) -> None:
        normalized = level.upper()
        theme = get_theme_manager().current
        color_key = _LOG_COLORS.get(normalized, "text_secondary")
        color = getattr(theme, color_key, theme.text_secondary)
        prefix = _LOG_PREFIXES.get(normalized, "[INFO]")
        self._log_view.append(f'<span style="color:{color}">{prefix} {msg}</span>')

    def _apply_detected_options(self, report: DetectReport) -> None:
        """只开放检测报告中确实存在问题的修复类别。"""
        chunk_problem = report.chunks_damaged > 0 or bool(report.unreadable_regions)
        player_problem = report.players_with_issues > 0
        level_problem = not report.level_dat_ok
        for checkbox, has_problem in (
            (self._fix_chunks_checkbox, chunk_problem),
            (self._fix_players_checkbox, player_problem),
            (self._fix_level_dat_checkbox, level_problem),
        ):
            checkbox.setChecked(has_problem)
            checkbox.setEnabled(has_problem)
        self._has_detect_report = report.has_problems and not report.cancelled
        self._backup_checkbox.setEnabled(self._has_detect_report)
        self._repair_options.setEnabled(True)
        self._repair_button.setEnabled(self._has_detect_report and not self._busy)

    def _reset_detected_state(self) -> None:
        """使检测结果失效，并阻止对未知世界状态直接执行修复。"""
        self._has_detect_report = False
        self._repair_options.setEnabled(False)
        self._repair_button.setEnabled(False)

    # ── 存档选择回调 ──────────────────────────────

    def on_save_selected(self, path: str) -> None:
        """统一入口设置当前存档回调。"""
        self._controller.select_world(path)
        self._world_path_field.setText(path)
        self._reset_detected_state()
        self._world_info_card.setVisible(False)
        self._detect_result_card.setVisible(False)

    def on_save_cleared(self) -> None:
        """取消旧世界修复并清空路径及结果投影。"""
        self._controller.clear_world()
        self._world_path_field.clear()
        self._reset_detected_state()
        self._world_info_card.setVisible(False)
        self._detect_result_card.setVisible(False)
        self._result_text.setText("")
        self._repair_result_card.setVisible(False)
        self._log_card.setVisible(False)

    def dispose(self) -> None:
        """取消检测/修复任务并释放页面作用域。"""
        self._controller.close()
        self._task_scope.close()
