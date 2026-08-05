"""Qt 地图导出对话框：复用 MapExportService 与框架中立导出状态。"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Protocol

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from app.presenters.map_export_state import (
    MapExportState,
    begin_map_export,
    dispose_map_export,
    finish_map_export,
    invalidate_map_export,
    owns_map_export,
    request_map_export_cancel,
)
from app.qtui.components.buttons import btn_ghost, btn_primary
from app.qtui.context import (
    QtDialogPort,
    QtFileDialogPort,
    QtProgressPort,
    QtRuntimePort,
    QtTranslationPort,
)
from app.qtui.utils import run_on_ui
from app.services.execution_runtime import (
    ExecutionLane,
    RuntimeClosedError,
    TaskPriority,
    TaskQueueFullError,
)
from app.services.map_export_service import (
    MapExportService,
    MapExportSpec,
    MapSelection,
    PIL_AVAILABLE,
)
from core.mca.map_models import MapUnit


class QtMapExportHost(
    QtTranslationPort,
    QtDialogPort,
    QtFileDialogPort,
    QtProgressPort,
    QtRuntimePort,
    Protocol,
):
    """地图导出对话框所需端口。"""


@dataclass(frozen=True)
class MapExportSession:
    """从当前地图上下文预填导出对话框的会话。"""

    world_path: Path
    dimension_id: str
    selected_region: Optional[tuple[int, int]] = None


class QtMapExportDialog:
    """模态导出 UI：绑定世界/维度/选区，在 CPU 通道异步渲染 PNG。"""

    def __init__(self, app: QtMapExportHost) -> None:
        """绑定应用端口并尝试初始化导出服务。"""
        self._app = app
        self._task_scope = app.execution_runtime.create_scope(
            "qt_map_export_dialog"
        )
        self._export_state = MapExportState()
        self._cancel_event: Optional[threading.Event] = None
        self._dialog: Optional[QDialog] = None
        self._session: Optional[MapExportSession] = None
        self._service: Optional[MapExportService] = None
        self._auto_output_path = ""
        if PIL_AVAILABLE:
            try:
                self._service = MapExportService()
            except ImportError:
                self._service = None
        self._dimension_label: QLabel
        self._output_path: QLineEdit
        self._map_type: QComboBox
        self._range_mode: QComboBox
        self._scale: QComboBox
        self._start_x: QLineEdit
        self._start_z: QLineEdit
        self._end_x: QLineEdit
        self._end_z: QLineEdit
        self._selection_host: QWidget
        self._result: QLabel
        self._select_output_btn: QWidget
        self._export_btn: QWidget
        self._cancel_export_btn: QWidget

    def open(self, session: MapExportSession) -> None:
        """打开并预填导出对话框。"""
        if self._export_state.is_disposed:
            return
        if self._service is None or not PIL_AVAILABLE:
            self._show_missing_pillow()
            return
        if self._export_state.is_running:
            self._app.warn_dialog(
                self._t("map_export.notice", "提示"),
                self._t(
                    "map_export.already_running",
                    "导出正在进行中，请稍候",
                ),
            )
            return
        self._session = session
        self._close_dialog()
        dialog = QDialog()
        dialog.setWindowTitle(self._t("map_export.title", "地图导出"))
        dialog.setModal(True)
        dialog.setMinimumWidth(560)
        layout = QVBoxLayout(dialog)
        layout.addLayout(self._build_form(session))
        layout.addWidget(self._build_actions())
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        buttons.clicked.connect(lambda _btn: self._close_dialog())
        layout.addWidget(buttons)
        self._dialog = dialog
        dialog.finished.connect(self._on_dialog_finished)
        dialog.show()

    def dispose(self) -> None:
        """取消进行中的导出并丢弃迟到回调。"""
        self._export_state = dispose_map_export(self._export_state)
        if self._cancel_event is not None:
            self._cancel_event.set()
        self._task_scope.close()
        self._close_dialog()

    def invalidate_session(self) -> None:
        """世界切换时取消导出并解绑会话，对话框仍可再次打开。"""
        if self._export_state.is_disposed:
            return
        was_running = self._export_state.is_running
        self._export_state = invalidate_map_export(self._export_state)
        cancel_event = self._cancel_event
        self._cancel_event = None
        self._session = None
        if cancel_event is not None:
            cancel_event.set()
        self._task_scope.cancel_all()
        self._close_dialog()
        if was_running:
            self._app.hide_progress()

    @staticmethod
    def default_output_path(world_path: Path, dimension_id: str) -> Path:
        """构建世界目录旁的默认 PNG 路径。"""
        suffix = "" if dimension_id == "overworld" else (
            "_" + dimension_id.replace(":", "_").replace("/", "_")
        )
        return world_path.parent / f"{world_path.name}{suffix}_map.png"

    def _t(self, key: str, default: str = "", **kwargs: object) -> str:
        return self._app.translate(key, default, **kwargs)

    def _build_form(self, session: MapExportSession) -> QFormLayout:
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._dimension_label = QLabel(self._t(
            "map_export.dimension_value",
            "维度: {dimension}",
            dimension=session.dimension_id,
        ))
        form.addRow(self._dimension_label)

        output_row = QHBoxLayout()
        self._output_path = QLineEdit()
        self._output_path.setReadOnly(True)
        default_output = self.default_output_path(
            session.world_path,
            session.dimension_id,
        )
        self._auto_output_path = str(default_output)
        self._output_path.setText(str(default_output))
        output_row.addWidget(self._output_path, 1)
        self._select_output_btn = btn_ghost(
            self._t("map_export.choose_output", "选择输出"),
            on_click=self._select_output,
        )
        output_row.addWidget(self._select_output_btn)
        form.addRow(self._t("map_export.output_file", "输出文件"), output_row)

        self._map_type = QComboBox()
        self._map_type.addItem(
            self._t("map_export.type_topview", "俯视图"),
            "topview",
        )
        form.addRow(self._t("map_export.map_type", "地图类型"), self._map_type)

        self._scale = QComboBox()
        for value, key, default in (
            ("1", "map_export.scale_original", "1:1（原始大小）"),
            ("2", "map_export.scale_half", "1:2（缩小一半）"),
            ("4", "map_export.scale_quarter", "1:4（缩小四分之一）"),
            ("8", "map_export.scale_eighth", "1:8（缩小八分之一）"),
            ("16", "", "1:16"),
            ("32", "", "1:32"),
        ):
            label = self._t(key, default) if key else default
            self._scale.addItem(label, value)
        self._scale.setCurrentIndex(2)
        form.addRow(self._t("map_export.scale", "缩放比例"), self._scale)

        self._range_mode = QComboBox()
        for value, key, default in (
            ("full", "map_export.range_full", "完整维度"),
            ("region", "map_export.range_region", "区域坐标矩形"),
            ("chunk", "map_export.range_chunk", "区块坐标矩形"),
            ("block", "map_export.range_block", "方块坐标矩形"),
        ):
            self._range_mode.addItem(self._t(key, default), value)
        has_region = session.selected_region is not None
        self._range_mode.setCurrentIndex(1 if has_region else 0)
        self._range_mode.currentIndexChanged.connect(self._on_range_mode_changed)
        form.addRow(self._t("map_export.range", "导出范围"), self._range_mode)

        region = session.selected_region or (0, 0)
        self._selection_host = QWidget()
        selection = QHBoxLayout(self._selection_host)
        selection.setContentsMargins(0, 0, 0, 0)
        self._start_x = QLineEdit(str(region[0]))
        self._start_z = QLineEdit(str(region[1]))
        self._end_x = QLineEdit(str(region[0]))
        self._end_z = QLineEdit(str(region[1]))
        for field, label in (
            (self._start_x, self._t("map_export.start_x", "起点 X")),
            (self._start_z, self._t("map_export.start_z", "起点 Z")),
            (self._end_x, self._t("map_export.end_x", "终点 X")),
            (self._end_z, self._t("map_export.end_z", "终点 Z")),
        ):
            field.setPlaceholderText(label)
            selection.addWidget(field)
        self._selection_host.setVisible(has_region)
        form.addRow(self._selection_host)

        self._result = QLabel("")
        self._result.setWordWrap(True)
        self._result.setProperty("role", "muted")
        form.addRow(self._result)
        return form

    def _build_actions(self) -> QWidget:
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        self._export_btn = btn_primary(
            self._t("map_export.start", "开始导出"),
            on_click=self._start_export,
        )
        self._cancel_export_btn = btn_ghost(
            self._t("map_export.cancel_export", "取消导出"),
            on_click=self._cancel_export,
        )
        self._cancel_export_btn.setEnabled(False)
        row.addWidget(self._export_btn)
        row.addWidget(self._cancel_export_btn)
        row.addStretch(1)
        return host

    def _on_range_mode_changed(self, _index: int) -> None:
        mode = self._range_mode.currentData()
        self._selection_host.setVisible(mode != "full")

    def _select_output(self) -> None:
        try:
            path = self._app.save_file(
                title=self._t("map_export.save_dialog_title", "保存地图"),
                default_ext=".png",
                file_types=[
                    (
                        self._t("map_export.png_files", "PNG 图片"),
                        "*.png",
                    ),
                    (
                        self._t("map_export.all_files", "所有文件"),
                        "*.*",
                    ),
                ],
            )
            if path:
                self._output_path.setText(path)
                self._auto_output_path = ""
        except Exception as exc:
            self._app.error_dialog(
                self._t("map_export.error", "错误"),
                self._t(
                    "map_export.file_selection_failed",
                    "选择文件失败: {error}",
                    error=exc,
                ),
            )

    def _build_export_spec(self, map_type: str, scale: int) -> MapExportSpec:
        session = self._require_session()
        mode = str(self._range_mode.currentData() or "full")
        selection = None
        if mode != "full":
            units: dict[str, MapUnit] = {
                "block": "block",
                "chunk": "chunk",
                "region": "region",
            }
            unit = units.get(mode)
            if unit is None:
                raise ValueError(self._t(
                    "map_export.unsupported_range",
                    "不支持的地图导出范围: {mode}",
                    mode=mode,
                ))
            selection = MapSelection(
                int(self._start_x.text().strip() or "0"),
                int(self._start_z.text().strip() or "0"),
                int(self._end_x.text().strip() or "0"),
                int(self._end_z.text().strip() or "0"),
                unit=unit,
            )
        return MapExportSpec(
            dimension_id=session.dimension_id,
            style=map_type,
            scale=scale,
            selection=selection,
        )

    def _require_session(self) -> MapExportSession:
        if self._session is None:
            raise RuntimeError("export dialog has no map session")
        return self._session

    def _cancel_export(self) -> None:
        if self._cancel_event is None or not self._export_state.is_running:
            return
        self._export_state = request_map_export_cancel(self._export_state)
        self._cancel_event.set()
        self._cancel_export_btn.setEnabled(False)
        self._result.setText(self._t(
            "map_export.cancelling",
            "正在取消导出...",
        ))

    def _start_export(self) -> None:
        if self._export_state.is_disposed or self._service is None:
            return
        if self._export_state.is_running:
            self._app.warn_dialog(
                self._t("map_export.notice", "提示"),
                self._t(
                    "map_export.already_running",
                    "导出正在进行中，请稍候",
                ),
            )
            return
        session = self._session
        if session is None:
            return
        output_path = self._output_path.text().strip()
        if not output_path:
            self._app.warn_dialog(
                self._t("map_export.notice", "提示"),
                self._t(
                    "map_export.select_output_first",
                    "请先选择输出文件",
                ),
            )
            return
        map_type = str(self._map_type.currentData() or "topview")
        scale = self._resolve_export_scale()
        try:
            spec = self._build_export_spec(map_type, scale)
        except (TypeError, ValueError) as exc:
            self._app.warn_dialog(
                self._t("map_export.invalid_range", "导出范围无效"),
                str(exc),
            )
            return
        self._export_state = begin_map_export(self._export_state)
        generation = self._export_state.generation
        cancel_event = threading.Event()
        self._cancel_event = cancel_event
        self._set_export_controls_enabled(False)
        self._result.setText(self._t("map_export.exporting", "正在导出地图..."))
        try:
            self._task_scope.submit(
                "export_map",
                lambda _token: self._export_thread(
                    session.world_path,
                    Path(output_path),
                    spec,
                    cancel_event,
                    generation,
                ),
                lane=ExecutionLane.CPU,
                priority=TaskPriority.INTERACTIVE,
            )
        except (RuntimeClosedError, TaskQueueFullError) as error:
            cancel_event.set()
            self._reset_export_state(generation)
            self._show_export_failure(error, "map_export.failed")

    def _resolve_export_scale(self) -> int:
        try:
            scale = int(str(self._scale.currentData() or "4"))
            if scale not in {1, 2, 4, 8, 16, 32}:
                scale = 4
        except (ValueError, TypeError):
            scale = 4
            self._app.warn_dialog(
                self._t("map_export.notice", "提示"),
                self._t(
                    "map_export.invalid_scale",
                    "缩放比例无效，使用默认值 1:4",
                ),
            )
        return scale

    def _set_export_controls_enabled(self, enabled: bool) -> None:
        controls = (
            self._select_output_btn,
            self._export_btn,
            self._map_type,
            self._scale,
            self._range_mode,
            self._start_x,
            self._start_z,
            self._end_x,
            self._end_z,
        )
        for control in controls:
            control.setEnabled(enabled)
        self._cancel_export_btn.setEnabled(not enabled)

    def _export_thread(
        self,
        world_path: Path,
        output_path: Path,
        spec: MapExportSpec,
        cancel_event: threading.Event,
        generation: int,
    ) -> None:
        try:
            self._run_for_generation(
                generation,
                self._app.show_progress,
                self._t("map_export.exporting", "正在导出地图..."),
            )

            def progress_callback(value: float, msg: str) -> None:
                self._run_for_generation(
                    generation,
                    self._app.update_progress_with_task,
                    msg or self._t("map_export.progress_task", "导出地图"),
                    value,
                )

            assert self._service is not None
            results = self._service.export_map(
                world_path=world_path,
                output_path=output_path,
                spec=spec,
                progress_callback=progress_callback,
                cancel_event=cancel_event,
            )
            self._run_for_generation(
                generation,
                self._finish_export,
                generation,
                results,
            )
        except Exception as exc:
            self._run_for_generation(
                generation,
                self._finish_export_error,
                generation,
                exc,
            )

    def _finish_export(
        self,
        generation: int,
        results: Mapping[str, Any],
    ) -> None:
        if results.get("success"):
            self._show_export_success(results)
        elif results.get("cancelled"):
            self._publish_export_result(
                self._t("map_export.cancelled", "导出已取消")
            )
        else:
            self._show_export_failure(
                results.get("error")
                or self._t("map_export.see_log", "请查看日志"),
                "map_export.failed_message",
            )
        self._reset_export_state(generation)

    def _show_export_success(self, results: Mapping[str, Any]) -> None:
        dimensions = results["dimensions"]
        self._publish_export_result(self._t(
            "map_export.completed_report",
            "导出完成！\n\n✓ 维度: {dimension}\n✓ 输出文件: {output}\n"
            "✓ 图像尺寸: {width} x {height}\n✓ 处理区块: {chunks}",
            dimension=results["dimension_id"],
            output=results["output_path"],
            width=dimensions[0],
            height=dimensions[1],
            chunks=results["chunks_processed"],
        ))
        self._app.info_dialog(
            self._t("map_export.completed", "完成"),
            self._t("map_export.completed_message", "地图导出完成！"),
        )

    def _finish_export_error(self, generation: int, error: Exception) -> None:
        self._show_export_failure(error, "map_export.failed")
        self._reset_export_state(generation)

    def _show_export_failure(self, error: object, message_key: str) -> None:
        self._publish_export_result(self._t(
            "map_export.failed",
            "导出失败: {error}",
            error=error,
        ))
        self._app.error_dialog(
            self._t("map_export.error", "错误"),
            self._t(message_key, "地图导出失败", error=error),
        )

    def _publish_export_result(self, message: str) -> None:
        if self._dialog is not None:
            self._result.setText(message)
        self._app.hide_progress()

    def _reset_export_state(self, generation: int) -> None:
        self._export_state = finish_map_export(self._export_state, generation)
        self._cancel_event = None
        if self._dialog is not None:
            self._set_export_controls_enabled(True)

    def _is_current_generation(self, generation: int) -> bool:
        return owns_map_export(self._export_state, generation)

    def _run_for_generation(
        self,
        generation: int,
        callback: Callable[..., object],
        *args: object,
    ) -> None:
        if not self._is_current_generation(generation):
            return

        def guarded() -> None:
            if self._is_current_generation(generation):
                callback(*args)

        run_on_ui(guarded)

    def _show_missing_pillow(self) -> None:
        self._app.error_dialog(
            self._t("map_export.missing_dependency", "缺少依赖库"),
            self._t(
                "map_export.pillow_required",
                "地图导出功能需要 Pillow 库支持",
            )
            + "\n\npip install Pillow",
        )

    def _close_dialog(self) -> None:
        dialog = self._dialog
        if dialog is None:
            return
        self._dialog = None
        dialog.close()

    def _on_dialog_finished(self, _result: int) -> None:
        self._dialog = None


__all__ = ["MapExportSession", "QtMapExportDialog", "QtMapExportHost"]
