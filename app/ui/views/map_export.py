"""Map Export View - 地图导出视图"""
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping, Optional

import flet as ft

from app.ui.theme import THEME
from app.ui.icons import IconSet
from app.ui.components.buttons import btn_primary, btn_ghost
from app.ui.components.fields import text_field, current_save_field, dropdown
from app.ui.components.cards import card, section_title
from app.ui.components.layout import page_header
from app.ui.utils import run_on_ui, safe_update
from app.ui.view_actions import ViewAction
from app.services.map_export_service import (
    MapExportService,
    MapExportSpec,
    MapSelection,
    PIL_AVAILABLE,
)
from core.region_utils import discover_dimension_region_dirs
from core.mca.map_models import MapUnit

if TYPE_CHECKING:
    from app.application import Application


class MapExportView(ft.Column):
    """地图导出视图"""

    def __init__(self, app: "Application") -> None:
        super().__init__(spacing=20, scroll=ft.ScrollMode.AUTO)
        self.app = app
        self._exporting = False
        self._auto_output_path = ""
        self._cancel_event: Optional[threading.Event] = None
        self._task_generation = 0
        self._disposed = False

        # 检查依赖
        if not PIL_AVAILABLE:
            self._build_missing_dependency_ui()
            return

        self.service = MapExportService()
        self.expand = True

        # 配置选项
        self._world_path_field = current_save_field(
            label=self.app.translate("map_export.current_save", "当前存档"),
            hint_text=self.app.translate(
                "map_export.current_save_hint",
                "请通过侧边栏设置要导出的当前存档目录",
            ),
        )

        self._output_path_field = text_field(
            label=self.app.translate("map_export.output_file", "输出文件"),
            hint_text=self.app.translate("map_export.output_hint", "选择保存位置"),
        )
        self._output_path_field.read_only = True

        self._map_type_dropdown = dropdown(
            label=self.app.translate("map_export.map_type", "地图类型"),
            options=[
                ft.dropdown.Option(
                    "topview",
                    self.app.translate("map_export.type_topview", "俯视图"),
                ),
                ft.dropdown.Option(
                    "terrain",
                    self.app.translate(
                        "map_export.type_terrain",
                        "地形图（高度着色）",
                    ),
                ),
            ],
            value="topview",
        )

        self._dimension_dropdown = dropdown(
            label=self.app.translate("map_export.dimension", "维度"),
            options=[],
            value="overworld",
            on_change=self._on_dimension_changed,
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
                    self.app.translate("map_export.range_region", "区域坐标矩形"),
                ),
                ft.dropdown.Option(
                    "chunk",
                    self.app.translate("map_export.range_chunk", "区块坐标矩形"),
                ),
                ft.dropdown.Option(
                    "block",
                    self.app.translate("map_export.range_block", "方块坐标矩形"),
                ),
            ],
            value="full",
            on_change=self._on_range_mode_changed,
        )
        self._selection_start_x = text_field(
            label=self.app.translate("map_export.start_x", "起点 X"),
            value="0",
            expand=True,
        )
        self._selection_start_z = text_field(
            label=self.app.translate("map_export.start_z", "起点 Z"),
            value="0",
            expand=True,
        )
        self._selection_end_x = text_field(
            label=self.app.translate("map_export.end_x", "终点 X"),
            value="0",
            expand=True,
        )
        self._selection_end_z = text_field(
            label=self.app.translate("map_export.end_z", "终点 Z"),
            value="0",
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
            visible=False,
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
                    self.app.translate("map_export.scale_eighth", "1:8（缩小八分之一）"),
                ),
                ft.dropdown.Option("16", "1:16"),
                ft.dropdown.Option("32", "1:32"),
            ],
            value="4",
        )

        # 结果显示
        self._result_text = ft.Text(
            "",
            size=13,
            color=THEME.text_secondary,
            selectable=True,
        )

        # 按钮
        self._select_output_btn = btn_ghost(
            self.app.translate("map_export.choose_output", "选择输出"),
            on_click=self._select_output,
        )
        self._export_btn = btn_primary(
            self.app.translate("map_export.start", "开始导出"),
            icon=ft.Icons.IMAGE_OUTLINED,
            on_click=self._start_export,
        )
        self._cancel_btn = ft.OutlinedButton(
            self.app.translate("map_export.cancel", "取消"),
            icon=ft.Icons.CANCEL_OUTLINED,
            disabled=True,
            on_click=self._cancel_export,
        )

        # 构建 UI
        self._build_ui()

    def get_top_actions(self) -> list[ViewAction]:
        if not PIL_AVAILABLE:
            return []
        return [
            ViewAction(
                self.app.translate("top_bar.start_export", "开始导出"),
                self._start_export,
            )
        ]

    def _build_missing_dependency_ui(self) -> None:
        """构建缺少依赖时的 UI"""
        self.spacing = 20
        self.expand = True

        error_card = card(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.ERROR_OUTLINE, size=48, color=THEME.error),
                            ft.Column(
                                [
                                    ft.Text(
                                        self.app.translate(
                                            "map_export.missing_dependency",
                                            "缺少依赖库",
                                        ),
                                        size=20,
                                        weight=ft.FontWeight.BOLD,
                                        color=THEME.text_primary,
                                    ),
                                    ft.Text(
                                        self.app.translate(
                                            "map_export.pillow_required",
                                            "地图导出功能需要 Pillow 库支持",
                                        ),
                                        size=13,
                                        color=THEME.text_secondary,
                                    ),
                                ],
                                spacing=4,
                            ),
                        ],
                        spacing=16,
                    ),
                    ft.Divider(height=20, color=THEME.border_subtle),
                    ft.Text(
                        self.app.translate(
                            "map_export.install_hint",
                            "请在命令行运行以下命令安装依赖：",
                        ),
                        size=13,
                        color=THEME.text_secondary,
                    ),
                    ft.Container(
                        content=ft.Text(
                            "pip install Pillow",
                            size=13,
                            color=THEME.mc_grass,
                            font_family="monospace",
                            selectable=True,
                        ),
                        padding=12,
                        bgcolor=THEME.bg_secondary,
                        border_radius=8,
                    ),
                ],
                spacing=12,
            )
        )

        self.controls = [error_card]

    def _build_ui(self) -> None:
        """构建 UI"""
        header = page_header(
            self.app.translate("map_export.title", "地图导出"),
            ft.Text(
                self.app.translate(
                    "map_export.subtitle",
                    "将存档地图导出为 PNG 图片（俯视图/地形图）",
                ),
                size=12,
                color=THEME.text_muted),
            icon=IconSet.EXPORT,
        )

        # 配置卡片
        config_card = card(
            ft.Column(
                [
                    section_title(
                        self.app.translate("map_export.current_save_section", "当前存档")
                    ),
                    self._world_path_field,
                    ft.Container(height=12),
                    section_title(
                        self.app.translate("map_export.output_section", "输出设置")
                    ),
                    ft.Row(
                        [self._output_path_field, self._select_output_btn],
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.END,
                    ),
                    ft.Container(height=12),
                    section_title(
                        self.app.translate("map_export.options_section", "导出选项")
                    ),
                    ft.Row(
                        [
                            self._dimension_dropdown,
                            self._map_type_dropdown,
                            self._scale_dropdown,
                        ],
                        spacing=12,
                    ),
                    ft.Row([self._range_mode_dropdown], spacing=12),
                    self._selection_fields,
                    ft.Container(height=12),
                    ft.Row(
                        [self._export_btn, self._cancel_btn],
                        spacing=12,
                    ),
                ],
                spacing=12,
            )
        )

        # 结果卡片
        result_card = card(
            ft.Column(
                [
                    section_title(
                        self.app.translate("map_export.result_section", "导出结果")
                    ),
                    ft.Container(
                        content=self._result_text,
                        padding=12,
                        bgcolor=THEME.bg_secondary,
                        border_radius=8,
                    ),
                ],
                spacing=12,
            )
        )

        self.controls = [
            header,
            ft.Container(height=8),
            config_card,
            result_card,
        ]

        self._world_path_field.expand = True
        self._output_path_field.expand = True
        self._map_type_dropdown.expand = True
        self._scale_dropdown.expand = True
        self._dimension_dropdown.expand = True
        self._range_mode_dropdown.expand = True

    def _select_output(self, e: ft.ControlEvent) -> None:
        """选择输出文件"""
        try:
            path = self.app.save_file(
                title=self.app.translate("map_export.save_dialog_title", "保存地图"),
                default_ext=".png",
                file_types=[
                    (self.app.translate("map_export.png_files", "PNG 图片"), "*.png"),
                    (self.app.translate("map_export.all_files", "所有文件"), "*.*"),
                ],
            )
            if path:
                self._output_path_field.value = path
                self._auto_output_path = ""
                safe_update(self._output_path_field)
        except Exception as ex:
            self.app.error_dialog(
                self.app.translate("map_export.error", "错误"),
                self.app.translate(
                    "map_export.file_selection_failed",
                    "选择文件失败: {error}",
                    error=ex,
                ),
            )

    def _on_range_mode_changed(self, _event: ft.ControlEvent) -> None:
        mode = self._range_mode_dropdown.value or "full"
        self._selection_fields.visible = mode != "full"
        safe_update(self._selection_fields)

    def _on_dimension_changed(self, _event: ft.ControlEvent) -> None:
        if not self._auto_output_path:
            return
        world_value = self._world_path_field.value
        if not world_value:
            return
        path = self._default_output_path(
            Path(world_value),
            self._dimension_dropdown.value or "overworld",
        )
        self._auto_output_path = str(path)
        self._output_path_field.value = str(path)
        safe_update(self._output_path_field)

    def _build_export_spec(self, map_type: str, scale: int) -> MapExportSpec:
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
            dimension_id=self._dimension_dropdown.value or "overworld",
            style=map_type,
            scale=scale,
            selection=selection,
        )

    def _cancel_export(self, _event: ft.Event[ft.OutlinedButton]) -> None:
        if self._cancel_event is None or not self._exporting:
            return
        self._cancel_event.set()
        self._cancel_btn.disabled = True
        self._result_text.value = self.app.translate(
            "map_export.cancelling",
            "正在取消导出...",
        )
        safe_update(self._cancel_btn)
        safe_update(self._result_text)

    def _start_export(self, e: ft.ControlEvent) -> None:
        """开始导出"""
        if self._disposed:
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

        world_path = self._world_path_field.value
        if not world_path:
            self.app.warn_dialog(
                self.app.translate("map_export.notice", "提示"),
                self.app.translate(
                    "map_export.select_save_first",
                    "请先通过侧边栏设置当前存档目录",
                ),
            )
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

        # 启动导出线程
        map_type = self._map_type_dropdown.value or "topview"
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
        self._cancel_event = threading.Event()
        self._set_export_controls_enabled(False)
        self._result_text.value = ""
        self._result_text.update()

        thread = threading.Thread(
            target=self._export_thread,
            args=(
                Path(world_path),
                Path(output_path),
                spec,
                self._cancel_event,
                generation,
            ),
            daemon=True,
        )
        thread.start()

    def _set_export_controls_enabled(self, enabled: bool) -> None:
        controls = (
            self._select_output_btn,
            self._export_btn,
            self._cancel_btn,
            self._map_type_dropdown,
            self._scale_dropdown,
            self._dimension_dropdown,
            self._range_mode_dropdown,
            self._selection_start_x,
            self._selection_start_z,
            self._selection_end_x,
            self._selection_end_z,
        )
        for control in controls:
            control.disabled = enabled if control is self._cancel_btn else not enabled
            safe_update(control)

    def _export_thread(
            self,
            world_path: Path,
            output_path: Path,
            spec: MapExportSpec,
            cancel_event: threading.Event,
            generation: int) -> None:
        """导出线程"""
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
                    msg or self.app.translate("map_export.progress_task", "导出地图"),
                    value,
                )

            def log_callback(msg: str, level: str) -> None:
                pass

            results = self.service.export_map(
                world_path=world_path,
                output_path=output_path,
                spec=spec,
                progress_callback=progress_callback,
                log_callback=log_callback,
                cancel_event=cancel_event,
            )
            self._run_for_generation(generation, self._finish_export, results)

        except Exception as ex:
            self._run_for_generation(generation, self._finish_export_error, ex)

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
                "map_export.failed", "导出失败: {error}", error=error
            )
        )
        self.app.error_dialog(
            self.app.translate("map_export.error", "错误"),
            self.app.translate(message_key, "地图导出失败", error=error),
        )

    def _publish_export_result(self, message: str) -> None:
        self._result_text.value = message
        self._result_text.update()
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

    def on_save_selected(self, path: str) -> None:
        """统一入口设置当前存档回调"""
        try:
            self._world_path_field.value = path
            safe_update(self._world_path_field)
            dimensions = discover_dimension_region_dirs(Path(path))
            self._dimension_dropdown.options = [
                ft.dropdown.Option(item.id, item.name)
                for item in dimensions
            ]
            available_ids = {item.id for item in dimensions}
            if self._dimension_dropdown.value not in available_ids:
                self._dimension_dropdown.value = (
                    "overworld"
                    if "overworld" in available_ids
                    else next(iter(available_ids), None)
                )
            safe_update(self._dimension_dropdown)
            if (
                not self._output_path_field.value
                or self._output_path_field.value == self._auto_output_path
            ):
                world_path = Path(path)
                output = self._default_output_path(
                    world_path,
                    self._dimension_dropdown.value or "overworld",
                )
                self._auto_output_path = str(output)
                self._output_path_field.value = str(output)
                safe_update(self._output_path_field)
        except Exception:
            pass

    @staticmethod
    def _default_output_path(world_path: Path, dimension_id: str) -> Path:
        suffix = "" if dimension_id == "overworld" else (
            "_" + dimension_id.replace(":", "_").replace("/", "_")
        )
        return world_path.parent / f"{world_path.name}{suffix}_map.png"

    def dispose(self) -> None:
        """请求停止仍在后台运行的地图导出。"""
        self._disposed = True
        self._task_generation += 1
        self._exporting = False
        if self._cancel_event is not None:
            self._cancel_event.set()
