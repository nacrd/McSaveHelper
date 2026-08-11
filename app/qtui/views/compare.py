"""存档对比视图（Qt 版，对应 Flet 树同名视图）。

双世界差异对比：level.dat、玩家与区域文件。
状态机复用 ``app.presenters.compare_view_state``。
"""
from __future__ import annotations

from concurrent.futures import CancelledError
from pathlib import Path
from typing import Optional, Protocol

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.presenters.compare_view_state import (
    CompareGroupState,
    begin_compare,
    clear_compare_baseline,
    complete_compare,
    fail_compare,
    initial_compare_state,
    invalidate_compare,
    select_compare_baseline,
)
from app.qtui.components.buttons import btn_ghost
from app.qtui.components.cards import card, muted_label, section_title
from app.qtui.components.layout import page_header
from app.qtui.context import (
    QtDialogPort,
    QtFileDialogPort,
    QtRuntimePort,
    QtTranslationPort,
)
from app.qtui.theme import get_theme_manager
from app.qtui.utils import run_on_ui
from app.qtui.view_actions import QtViewAction
from app.services.execution_runtime import (
    CancellationToken,
    ExecutionLane,
    OperationCancelledError,
    OperationHandle,
    TaskPriority,
)
from app.services.world_compare_service import WorldCompareResult, WorldCompareService


class CompareHost(
    QtTranslationPort,
    QtDialogPort,
    QtFileDialogPort,
    QtRuntimePort,
    Protocol,
):
    """对比页面所需的端口。"""

    @property
    def world_compare(self) -> WorldCompareService:
        """返回世界对比服务。"""
        ...


class CompareView(QScrollArea):
    """双世界差异对比页：level.dat、玩家与区域文件。"""

    def __init__(self, app: CompareHost) -> None:
        """绑定应用与对比服务。

        Args:
            app: 对比页面所需的 UI、运行时和对比服务端口。
        """
        super().__init__()
        self.app = app
        self._task_scope = app.execution_runtime.create_scope("compare_view")
        self._service = app.world_compare
        self._state = initial_compare_state()

        self.setWidgetResizable(True)
        self._build()

    def get_top_actions(self) -> list[QtViewAction]:
        """顶栏「开始对比」动作。"""
        return [
            QtViewAction(
                self.app.translate("top_bar.start_compare", "开始对比"),
                self._compare,
            )
        ]

    def _build(self) -> None:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)

        layout.addWidget(page_header(
            "存档对比",
            "比较两个世界的 level.dat、玩家数据和区域文件差异",
            icon="⚖️",
        ))

        # ─── 路径卡片 ─────────────────────────────
        picker_body = QWidget()
        picker_layout = QVBoxLayout(picker_body)
        picker_layout.setContentsMargins(0, 0, 0, 0)
        picker_layout.setSpacing(10)

        picker_layout.addWidget(QLabel("基准存档"))
        self._left_field = QLineEdit()
        self._left_field.setPlaceholderText(
            "请通过侧边栏「设置当前存档」设置基准存档"
        )
        picker_layout.addWidget(self._left_field)

        picker_layout.addWidget(QLabel("目标存档"))
        right_row = QWidget()
        right_layout = QHBoxLayout(right_row)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)
        self._right_field = QLineEdit()
        self._right_field.setPlaceholderText("指定要对比的目标存档目录")
        browse_button = btn_ghost("浏览对比目标", on_click=self._pick_target)
        right_layout.addWidget(self._right_field, 1)
        right_layout.addWidget(browse_button)
        picker_layout.addWidget(right_row)

        picker_layout.addWidget(muted_label(
            "设置两份存档后，可通过标题栏“开始对比”执行。"
        ))
        layout.addWidget(card(picker_body, padding=16))

        # ─── 结果卡片 ─────────────────────────────
        result_body = QWidget()
        result_layout = QVBoxLayout(result_body)
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.setSpacing(8)
        result_layout.addWidget(section_title("结果"))
        self._summary = QLabel(self._state.summary)
        self._summary.setProperty("role", "muted")
        result_layout.addWidget(self._summary)
        self._result_layout = QVBoxLayout()
        self._result_layout.setSpacing(8)
        result_layout.addLayout(self._result_layout)
        layout.addWidget(card(result_body, padding=16))

        layout.addStretch(1)
        self.setWidget(content)

    def _pick_target(self) -> None:
        path = self.app.pick_directory()
        if path:
            self._right_field.setText(path)

    def _compare(self) -> None:
        try:
            if self._state.is_comparing:
                self.app.warn_dialog("提示", "对比正在进行中，请稍候。")
                return
            paths = self._validated_compare_paths()
            if paths is None:
                return
            self._state = begin_compare(self._state, *paths)
            generation = self._state.generation
            self._render_state()
            handle = self._task_scope.submit(
                "compare_worlds",
                lambda token: self._run_compare(*paths, token),
                lane=ExecutionLane.IO,
                priority=TaskPriority.INTERACTIVE,
            )
            handle.add_done_callback(
                lambda completed: self._finish_compare_task(
                    completed,
                    generation,
                )
            )
        except Exception as exc:
            self._handle_compare_error(exc, self._state.generation)

    def _validated_compare_paths(self) -> Optional[tuple[Path, Path]]:
        left_text = self._left_field.text().strip()
        right_text = self._right_field.text().strip()
        if not left_text:
            self.app.warn_dialog("提示", "请先通过侧边栏设置有效基准存档目录。")
            return None
        if not right_text:
            self.app.warn_dialog("提示", "请指定包含 level.dat 的有效目标存档目录。")
            return None
        return Path(left_text), Path(right_text)

    def _run_compare(
        self,
        left: Path,
        right: Path,
        token: CancellationToken,
    ) -> WorldCompareResult:
        """在 I/O 通道校验路径并生成纯对比结果。"""
        token.raise_if_cancelled()
        self._validate_world_path(left, "基准")
        self._validate_world_path(right, "目标")
        result = self._service.compare_worlds(left, right)
        token.raise_if_cancelled()
        return result

    @staticmethod
    def _validate_world_path(path: Path, label: str) -> None:
        if not (path / "level.dat").is_file():
            raise ValueError(f"{label}存档目录缺少 level.dat: {path}")

    def _finish_compare_task(
        self,
        handle: OperationHandle[WorldCompareResult],
        generation: int,
    ) -> None:
        if handle.cancelled:
            return
        try:
            result = handle.result()
        except (CancelledError, OperationCancelledError):
            return
        except Exception as error:
            run_on_ui(self._handle_compare_error, error, generation)
            return
        run_on_ui(self._apply_compare_result, result, generation)

    def _apply_compare_result(
        self,
        result: WorldCompareResult,
        generation: int,
    ) -> None:
        next_state = complete_compare(self._state, result, generation)
        if next_state is self._state:
            return
        self._state = next_state
        self._render_state()

    def _handle_compare_error(
        self,
        error: Exception,
        generation: int,
    ) -> None:
        next_state = fail_compare(self._state, generation)
        if next_state is self._state:
            return
        self._state = next_state
        self._render_state()
        self.app.handle_exception(error, title="存档对比失败")

    def _render_state(self) -> None:
        self._summary.setText(self._state.summary)
        self._clear_result_groups()
        for group in self._state.groups:
            self._result_layout.addWidget(self._group(group))
        self._result_layout.addStretch(1)

    def _clear_result_groups(self) -> None:
        """清空结果分组（幂等）。"""
        while self._result_layout.count():
            item = self._result_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _group(self, group: CompareGroupState) -> QWidget:
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)

        title = QLabel(group.title)
        title.setStyleSheet("font-size: 14px; font-weight: 600;")
        body_layout.addWidget(title)

        if not group.items:
            placeholder = QLabel("✅ 未发现差异 — 该分组中的两份存档数据一致")
            placeholder.setProperty("role", "muted")
            body_layout.addWidget(placeholder)
        else:
            theme = get_theme_manager().current
            for item in group.items:
                row_body = QWidget()
                row_layout = QVBoxLayout(row_body)
                row_layout.setContentsMargins(8, 8, 8, 8)
                row_layout.setSpacing(2)
                name = QLabel(item.name)
                name.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {theme.mc_gold};")
                left = QLabel(f"基准: {item.left}")
                left.setStyleSheet(f"font-size: 11px; color: {theme.text_secondary};")
                right = QLabel(f"目标: {item.right}")
                right.setStyleSheet(f"font-size: 11px; color: {theme.text_secondary};")
                row_layout.addWidget(name)
                row_layout.addWidget(left)
                row_layout.addWidget(right)
                body_layout.addWidget(row_body)
        return card(body, padding=12)

    def on_save_selected(self, path: str) -> None:
        """切换基准存档并使旧世界的对比结果失效。"""
        self._state = select_compare_baseline(self._state, Path(path))
        self._task_scope.cancel_all()
        self._left_field.setText(path)
        self._render_state()

    def on_save_cleared(self) -> None:
        """取消对比并清空已选择的基准世界。"""
        self._state = clear_compare_baseline(self._state)
        self._task_scope.cancel_all()
        self._left_field.clear()
        self._render_state()

    def dispose(self) -> None:
        """取消页面拥有的对比任务；可重复调用。"""
        self._state = invalidate_compare(self._state)
        self._task_scope.close()
