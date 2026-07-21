"""Map export dialog embedded in the Explorer region map."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping, Optional, Tuple

import flet as ft

from app.services.map_export_service import (
    MapExportService,
    MapExportSpec,
    MapSelection,
    PIL_AVAILABLE,
)
from app.services.execution_runtime import ExecutionLane, TaskPriority
from app.ui.components.buttons import btn_ghost, btn_primary
from app.ui.components.fields import dropdown, text_field
from app.ui.theme import THEME
from app.ui.utils import run_on_ui, safe_update
from core.mca.map_models import MapUnit

if TYPE_CHECKING:
    from app.application import Application


@dataclass(frozen=True)
class MapExportSession:
    """Map context used to prefill the export dialog."""

    world_path: Path
    dimension_id: str
    selected_region: Optional[Tuple[int, int]] = None


class MapExportDialog:
    """Modal export UI that reuses the map's current world/dimension/selection."""

    def __init__(self, app: "Application") -> None:
        """绑定应用壳并尝试初始化导出服务。

        Args:
            app: 应用组合根（对话框、翻译、文件选择）。
        """
        self.app = app
        self._task_scope = app.execution_runtime.create_scope(
            "map_export_dialog"
        )
        self._exporting = False
        self._auto_output_path = ""
        self._cancel_event: Optional[threading.Event] = None
        self._task_generation = 0
        self._disposed = False
        self._dialog: Optional[ft.AlertDialog] = None
        self._session: Optional[MapExportSession] = None
        self._service: Optional[MapExportService] = None
        if PIL_AVAILABLE:
            try:
                self._service = MapExportService()
            except ImportError:
                self._service = None

    def open(self, session: MapExportSession) -> None:
        """Open the export dialog prefilled from the active map session."""
        if self._disposed:
            return
        if self._service is None or not PIL_AVAILABLE:
            self._show_missing_pillow()
            return
        if self._exporting:
            self.app.warn_dialog(
                self.app.translate("map_export.notice", "提示"),
                self.app.translate(
                    "map_export.already_running",
                    "导出正在进行中，请稍候",
                ),
            )
            return
        self._session = session
        self._build_fields(session)
        self._dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(self.app.translate("map_export.title", "地图导出")),
            content=self._build_dialog_body(),
            actions=self._build_dialog_actions(),
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.app.page.show_dialog(self._dialog)

    def dispose(self) -> None:
        """Cancel in-flight export and drop late UI callbacks."""
        self._disposed = True
        self._task_generation += 1
        self._exporting = False
        if self._cancel_event is not None:
            self._cancel_event.set()
        self._task_scope.close()
        self._close_dialog()

    def _show_missing_pillow(self) -> None:
        self.app.error_dialog(
            self.app.translate("map_export.missing_dependency", "缺少依赖库"),
            self.app.translate(
                "map_export.pillow_required",
                "地图导出功能需要 Pillow 库支持",
            )
            + "\n\npip install Pillow",
        )

    def _build_fields(self, session: MapExportSession) -> None:
        self._dimension_text = ft.Text(
            self.app.translate(
                "map_export.dimension_value",
                "维度: {dimension}",
                dimension=session.dimension_id,
            ),
            size=13,
            color=THEME.text_secondary,
        )
        self._output_path_field = text_field(
            label=self.app.translate("map_export.output_file", "输出文件"),
            hint_text=self.app.translate("map_export.output_hint", "选择保存位置"),
        )
        self._output_path_field.read_only = True
        self._output_path_field.expand = True
        # Export always uses the map's topview renderer; keep the field for
        # future styles but only offer the shared map surface path.
        self._map_type_dropdown = dropdown(
            label=self.app.translate("map_export.map_type", "地图类型"),
            options=[
                ft.dropdown.Option(
                    "topview",
                    self.app.translate("map_export.type_topview", "俯视图"),
                ),
            ],
            value="topview",
        )
        self._range_mode_dropdown = dropdown(
            label=self.app.translate("map_export.range", "导出范围"),
            options=[
                ft.dropdown.Option(
                    "full",
                    self.app.translate("map_export.range_full", "完整维度"),
                ),
                ft.dropdown.Option(
                    "region",
                    self.app.translate(
                        "map_export.range_region",
                        "区域坐标矩形",
                    ),
                ),
                ft.dropdown.Option(
                    "chunk",
                    self.app.translate(
                        "map_export.range_chunk",
                        "区块坐标矩形",
                    ),
                ),
                ft.dropdown.Option(
                    "block",
                    self.app.translate(
                        "map_export.range_block",
                        "方块坐标矩形",
                    ),
                ),
            ],
            value="region" if session.selected_region is not None else "full",
            on_change=self._on_range_mode_changed,
        )
        region = session.selected_region or (0, 0)
        self._selection_start_x = text_field(
            label=self.app.translate("map_export.start_x", "起点 X"),
            value=str(region[0]),
            expand=True,
        )
        self._selection_start_z = text_field(
            label=self.app.translate("map_export.start_z", "起点 Z"),
            value=str(region[1]),
            expand=True,
        )
        self._selection_end_x = text_field(
            label=self.app.translate("map_export.end_x", "终点 X"),
            value=str(region[0]),
            expand=True,
        )
        self._selection_end_z = text_field(
            label=self.app.translate("map_export.end_z", "终点 Z"),
            value=str(region[1]),
            expand=True,
        )
        self._selection_fields = ft.Container(
            content=ft.Row(
                [
                    self._selection_start_x,
                    self._selection_start_z,
                    self._selection_end_x,
                    self._selection_end_z,
                ],
                spacing=8,
            ),
            visible=session.selected_region is not None,
        )
        self._scale_dropdown = dropdown(
            label=self.app.translate("map_export.scale", "缩放比例"),
            options=[
                ft.dropdown.Option(
                    "1",
                    self.app.translate("map_export.scale_original", "1:1（原始大小）"),
                ),
                ft.dropdown.Option(
                    "2",
                    self.app.translate("map_export.scale_half", "1:2（缩小一半）"),
                ),
                ft.dropdown.Option(
                    "4",
                    self.app.translate(
                        "map_export.scale_quarter",
                        "1:4（缩小四分之一）",
                    ),
                ),
                ft.dropdown.Option(
                    "8",
                    self.app.translate(
                        "map_export.scale_eighth",
                        "1:8（缩小八分之一）",
                    ),
                ),
                ft.dropdown.Option("16", "1:16"),
                ft.dropdown.Option("32", "1:32"),
            ],
            value="4",
        )
        self._result_text = ft.Text(
            "",
            size=12,
            color=THEME.text_secondary,
            selectable=True,
        )
        self._select_output_btn = btn_ghost(
            self.app.translate("map_export.choose_output", "选择输出"),
            on_click=self._select_output,
        )
        self._export_btn = btn_primary(
            self.app.translate("map_export.start", "开始导出"),
            icon=ft.Icons.IMAGE_OUTLINED,
            on_click=self._start_export,
        )
        self._cancel_export_btn = ft.OutlinedButton(
            self.app.translate("map_export.cancel_export", "取消导出"),
            icon=ft.Icons.CANCEL_OUTLINED,
            disabled=True,
            on_click=self._cancel_export,
        )
        default_output = self._default_output_path(
            session.world_path,
            session.dimension_id,
        )
        self._auto_output_path = str(default_output)
        self._output_path_field.value = str(default_output)

    def _build_dialog_body(self) -> ft.Control:
        return ft.Container(
            content=ft.Column(
                [
                    self._dimension_text,
                    ft.Row(
                        [self._output_path_field, self._select_output_btn],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.END,
                    ),
                    ft.Row(
                        [self._map_type_dropdown, self._scale_dropdown],
                        spacing=8,
                    ),
                    self._range_mode_dropdown,
                    self._selection_fields,
                    self._result_text,
                    ft.Row(
                        [self._export_btn, self._cancel_export_btn],
                        spacing=8,
                    ),
                ],
                spacing=10,
                tight=True,
                scroll=ft.ScrollMode.AUTO,
            ),
            width=560,
            height=420,
        )

    def _build_dialog_actions(self) -> list[ft.Control]:
        return [
            ft.TextButton(
                self.app.translate("map_export.close", "关闭"),
                on_click=lambda _event: self._close_dialog(),
            ),
        ]

    def _close_dialog(self) -> None:
        dialog = self._dialog
        if dialog is None:
            return
        dialog.open = False
        self._dialog = None
        try:
            self.app.page.update()
        except RuntimeError:
            pass

    def _on_range_mode_changed(self, _event: ft.ControlEvent) -> None:
        mode = self._range_mode_dropdown.value or "full"
        self._selection_fields.visible = mode != "full"
        safe_update(self._selection_fields)

    def _select_output(self, _event: ft.ControlEvent) -> None:
        try:
            path = self.app.save_file(
                title=self.app.translate(
                    "map_export.save_dialog_title",
                    "保存地图",
                ),
                default_ext=".png",
                file_types=[
                    (
                        self.app.translate("map_export.png_files", "PNG 图片"),
                        "*.png",
                    ),
                    (
                        self.app.translate("map_export.all_files", "所有文件"),
                        "*.*",
                    ),
                ],
            )
            if path:
                self._output_path_field.value = path
                self._auto_output_path = ""
                safe_update(self._output_path_field)
        except Exception as exc:
            self.app.error_dialog(
                self.app.translate("map_export.error", "错误"),
                self.app.translate(
                    "map_export.file_selection_failed",
                    "选择文件失败: {error}",
                    error=exc,
                ),
            )

    def _build_export_spec(self, map_type: str, scale: int) -> MapExportSpec:
        session = self._require_session()
        mode = self._range_mode_dropdown.value or "full"
        selection = None
        if mode != "full":
            units: dict[str, MapUnit] = {
                "block": "block",
                "chunk": "chunk",
                "region": "region",
            }
            unit = units.get(mode)
            if unit is None:
                raise ValueError(
                    self.app.translate(
                        "map_export.unsupported_range",
                        "不支持的地图导出范围: {mode}",
                        mode=mode,
                    )
                )
            selection = MapSelection(
                int((self._selection_start_x.value or "0").strip()),
                int((self._selection_start_z.value or "0").strip()),
                int((self._selection_end_x.value or "0").strip()),
                int((self._selection_end_z.value or "0").strip()),
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

    def _cancel_export(self, _event: Any = None) -> None:
        if self._cancel_event is None or not self._exporting:
            return
        self._cancel_event.set()
        self._cancel_export_btn.disabled = True
        self._result_text.value = self.app.translate(
            "map_export.cancelling",
            "正在取消导出...",
        )
        safe_update(self._cancel_export_btn)
        safe_update(self._result_text)

    def _start_export(self, _event: Any = None) -> None:
        if self._disposed or self._service is None:
            return
        if self._exporting:
            self.app.warn_dialog(
                self.app.translate("map_export.notice", "提示"),
                self.app.translate(
                    "map_export.already_running",
                    "导出正在进行中，请稍候",
                ),
            )
            return
        session = self._session
        if session is None:
            return
        output_path = self._output_path_field.value
        if not output_path:
            self.app.warn_dialog(
                self.app.translate("map_export.notice", "提示"),
                self.app.translate(
                    "map_export.select_output_first",
                    "请先选择输出文件",
                ),
            )
            return
        map_type = self._map_type_dropdown.value or "topview"
        scale = self._resolve_export_scale()
        try:
            spec = self._build_export_spec(map_type, scale)
        except (TypeError, ValueError) as exc:
            self.app.warn_dialog(
                self.app.translate("map_export.invalid_range", "导出范围无效"),
                str(exc),
            )
            return
        self._exporting = True
        self._task_generation += 1
        generation = self._task_generation
        cancel_event = threading.Event()
        self._cancel_event = cancel_event
        self._set_export_controls_enabled(False)
        self._result_text.value = self.app.translate(
            "map_export.exporting",
            "正在导出地图...",
        )
        safe_update(self._result_text)
        self._task_scope.submit(
            "export_map",
            lambda token: self._export_thread(
                session.world_path,
                Path(str(output_path)),
                spec,
                cancel_event,
                generation,
            ),
            lane=ExecutionLane.CPU,
            priority=TaskPriority.INTERACTIVE,
        )

    def _resolve_export_scale(self) -> int:
        try:
            scale = int(self._scale_dropdown.value or "4")
            if scale not in [1, 2, 4, 8, 16, 32]:
                scale = 4
        except (ValueError, TypeError):
            scale = 4
            self.app.warn_dialog(
                self.app.translate("map_export.notice", "提示"),
                self.app.translate(
                    "map_export.invalid_scale",
                    "缩放比例无效，使用默认值 1:4",
                ),
            )
        return scale

    def _set_export_controls_enabled(self, enabled: bool) -> None:
        controls = (
            self._select_output_btn,
            self._export_btn,
            self._cancel_export_btn,
            self._map_type_dropdown,
            self._scale_dropdown,
            self._range_mode_dropdown,
            self._selection_start_x,
            self._selection_start_z,
            self._selection_end_x,
            self._selection_end_z,
        )
        for control in controls:
            control.disabled = (
                enabled if control is self._cancel_export_btn else not enabled
            )
            safe_update(control)

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
                self.app.show_progress,
                self.app.translate("map_export.exporting", "正在导出地图..."),
            )

            def progress_callback(value: float, msg: str) -> None:
                self._run_for_generation(
                    generation,
                    self.app.update_progress_with_task,
                    msg
                    or self.app.translate(
                        "map_export.progress_task",
                        "导出地图",
                    ),
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
            self._run_for_generation(generation, self._finish_export, results)
        except Exception as exc:
            self._run_for_generation(generation, self._finish_export_error, exc)

    def _finish_export(self, results: Mapping[str, Any]) -> None:
        if results["success"]:
            self._show_export_success(results)
        elif results.get("cancelled"):
            self._publish_export_result(
                self.app.translate("map_export.cancelled", "导出已取消")
            )
        else:
            self._show_export_failure(
                results.get("error")
                or self.app.translate("map_export.see_log", "请查看日志"),
                "map_export.failed_message",
            )
        self._reset_export_state()

    def _show_export_success(self, results: Mapping[str, Any]) -> None:
        dimensions = results["dimensions"]
        self._publish_export_result(
            self.app.translate(
                "map_export.completed_report",
                "导出完成！\n\n✓ 维度: {dimension}\n✓ 输出文件: {output}\n"
                "✓ 图像尺寸: {width} x {height}\n✓ 处理区块: {chunks}",
                dimension=results["dimension_id"],
                output=results["output_path"],
                width=dimensions[0],
                height=dimensions[1],
                chunks=results["chunks_processed"],
            )
        )
        self.app.info_dialog(
            self.app.translate("map_export.completed", "完成"),
            self.app.translate("map_export.completed_message", "地图导出完成！"),
        )

    def _finish_export_error(self, error: Exception) -> None:
        self._show_export_failure(error, "map_export.failed")
        self._reset_export_state()

    def _show_export_failure(self, error: object, message_key: str) -> None:
        self._publish_export_result(
            self.app.translate(
                "map_export.failed",
                "导出失败: {error}",
                error=error,
            )
        )
        self.app.error_dialog(
            self.app.translate("map_export.error", "错误"),
            self.app.translate(message_key, "地图导出失败", error=error),
        )

    def _publish_export_result(self, message: str) -> None:
        self._result_text.value = message
        safe_update(self._result_text)
        self.app.hide_progress()

    def _reset_export_state(self) -> None:
        self._exporting = False
        self._cancel_event = None
        self._task_generation += 1
        self._set_export_controls_enabled(True)

    def _is_current_generation(self, generation: int) -> bool:
        return not self._disposed and generation == self._task_generation

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

        run_on_ui(self.app.page, guarded)

    @staticmethod
    def default_output_path(world_path: Path, dimension_id: str) -> Path:
        """Build the default PNG path next to the world directory."""
        suffix = "" if dimension_id == "overworld" else (
            "_" + dimension_id.replace(":", "_").replace("/", "_")
        )
        return world_path.parent / f"{world_path.name}{suffix}_map.png"

    def _default_output_path(self, world_path: Path, dimension_id: str) -> Path:
        return self.default_output_path(world_path, dimension_id)
