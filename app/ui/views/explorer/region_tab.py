"""Region map tab mixin for ExplorerView.

Hosts the simplified map display (McaMapView) for browsing MCA regions.
"""
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

import flet as ft

from app.controllers.region_delete_controller import (
    RegionDeleteBusyError,
    RegionDeleteOutcome,
    RegionDeleteRequest,
    RegionDeleteStatus,
)
from app.services.execution_runtime import RuntimeClosedError, TaskQueueFullError
from app.ui.theme import THEME
from app.controllers.map_controller import MapController
from app.ui.utils import run_on_ui
from app.ui.views.explorer.utils import safe_update
from app.ui.views.explorer.map import McaMapView
from app.ui.views.explorer.map.export_dialog import MapExportDialog, MapExportSession
from app.ui.views.explorer.map.fullscreen import MapFullscreenController
from app.ui.views.explorer.mixin_context import ExplorerMixinHost
from app.ui.views.explorer.region_tab_chrome import (
    REGION_DISPLAY_HELP,
    build_map_fallback,
    build_region_legend_content,
    build_region_tab_chrome,
)
from core.mca.region_selection import format_region_selection
from core.mca.map_models import (
    MapMarker,
    MapViewState,
    MapViewStateSnapshot,
)
from core.mca.map_search import MapSearchError
from core.region_utils import DimensionInfo


class RegionTabMixin(ExplorerMixinHost):
    """Build and handle the Explorer region / map tab."""

    def _build_region_tab(self) -> None:
        map_view = self._create_region_map_view()
        chrome = self._create_region_tab_chrome(map_view)
        self._bind_region_tab_chrome(chrome)
        self._map_export_dialog = MapExportDialog(self.app)
        self._map_fullscreen_controller = (
            MapFullscreenController(
                page=self.app.page,
                map_view=self._map_view,
                inline_host=self._map_host,
                side_panel=self._region_side_panel,
                set_toggle_state=self._set_map_fullscreen_state,
                refresh=self._refresh_map,
                zoom_in=self._map_zoom_in,
                zoom_out=self._map_zoom_out,
                reset=self._map_reset_view,
                translate=self.app.translate,
            )
            if self._map_view is not None
            else None
        )
        self._selected_marker_id: Optional[str] = None
        self._marker_busy = False
        self._refresh_map_markers()

    def _create_region_map_view(self) -> ft.Control:
        try:
            self._map_view = McaMapView(
                map_service=self._map_service,
                execution_runtime=self.app.execution_runtime,
                on_selection_changed=self._on_region_selected,
                on_marker_selected=self._on_map_marker_selected,
                width=900,
                height=560,
                cache_registry=self.app.cache_registry,
            )
            return self._map_view
        except Exception:
            # Map canvas may fail to construct without optional deps; fall back.
            self._map_view = None
            return build_map_fallback(self.app.translate)

    def _create_region_tab_chrome(self, map_view: ft.Control) -> Any:
        return build_region_tab_chrome(
            map_content=map_view,
            on_dimension_changed=self._on_dimension_changed,
            on_display_mode_changed=self._change_region_display_mode,
            on_refresh=self._refresh_map,
            on_zoom_in=self._map_zoom_in,
            on_zoom_out=self._map_zoom_out,
            on_reset=self._map_reset_view,
            on_toggle_coordinates=self._toggle_map_coordinates,
            on_toggle_empty=self._toggle_map_empty_regions,
            on_toggle_fullscreen=self._toggle_map_fullscreen,
            on_fill_nbt=self._fill_selected_region_for_nbt,
            on_delete_region=self._delete_selected_region,
            on_search=self._search_map,
            on_toggle_markers=self._toggle_map_markers,
            on_add_marker=self._show_add_marker_dialog,
            on_delete_marker=self._delete_selected_marker,
            on_export=self._open_map_export_dialog,
            translate=self.app.translate,
        )

    def _bind_region_tab_chrome(self, chrome: Any) -> None:
        self._region_display_mode = "topview"
        self._dimension_dropdown = chrome.dimension_dropdown
        self._region_display_mode_dropdown = chrome.display_mode_dropdown
        self._map_search_field = chrome.search_field
        self._map_coord_btn = chrome.coord_button
        self._map_empty_btn = chrome.empty_button
        self._map_marker_btn = chrome.marker_button
        self._map_fullscreen_btn = chrome.fullscreen_button
        self._map_export_btn = chrome.export_button
        self._map_marker_list = chrome.marker_list
        self._map_marker_count_text = chrome.marker_count_text
        self._map_add_marker_btn = chrome.add_marker_button
        self._map_delete_marker_btn = chrome.delete_marker_button
        self._region_help_text = chrome.help_text
        self._region_stats_text = chrome.stats_text
        self._region_status_text = chrome.status_text
        self._region_legend_container = chrome.legend_container
        self._region_toolbar = chrome.toolbar
        self._map_host = chrome.map_host
        self._region_map_card = chrome.map_card
        self._region_left_panel = chrome.left_panel
        self._region_side_panel = chrome.side_panel
        self._region_layout = chrome.layout
        self._tab_region.content = self._region_layout
        self._tab_region.expand = True

    def _toggle_map_fullscreen(self) -> None:
        if self._map_fullscreen_controller is not None:
            self._map_fullscreen_controller.toggle()

    def _set_map_fullscreen_state(self, active: bool) -> None:
        button = self._map_fullscreen_btn
        label = self.app.translate(
            "map.exit_fullscreen" if active else "map.fullscreen",
            "退出全屏" if active else "全屏地图",
        )
        button.icon = ft.Icons.FULLSCREEN_EXIT if active else ft.Icons.FULLSCREEN
        button.tooltip = label
        button.selected = active
        safe_update(self._map_fullscreen_btn)

    def _dispose_region_tab(self) -> None:
        controller = getattr(self, "_map_fullscreen_controller", None)
        if controller is not None:
            controller.dispose()
        export_dialog = getattr(self, "_map_export_dialog", None)
        if export_dialog is not None:
            export_dialog.dispose()
        map_view = getattr(self, "_map_view", None)
        dispose_map = getattr(map_view, "dispose", None)
        if callable(dispose_map):
            dispose_map()

    def _open_map_export_dialog(self) -> None:
        """Open export dialog prefilled from the active map context."""
        if self.world_session is None:
            self.app.warn_dialog(
                self.app.translate("map.notice", "提示"),
                self.app.translate("map.select_save_first", "请先设置当前存档。"),
            )
            return
        dialog = getattr(self, "_map_export_dialog", None)
        if dialog is None:
            dialog = MapExportDialog(self.app)
            self._map_export_dialog = dialog
        dialog.open(
            MapExportSession(
                world_path=self.world_session.world_path,
                dimension_id=self._current_dimension or "overworld",
                selected_region=self._selected_region_coord,
            )
        )

    def _change_region_display_mode(self) -> None:
        mode = self._region_display_mode_dropdown.value or "topview"
        self._region_display_mode = mode
        controller = getattr(self, "_map_controller", None)
        if controller is not None:
            controller.set_style(mode)
        if self._map_view is not None and hasattr(self._map_view, "set_display_mode"):
            self._map_view.set_display_mode(mode)
        self._region_help_text.value = self._get_region_display_help(mode)
        self._region_legend_container.content = build_region_legend_content(
            self.app.translate
        )
        safe_update(self._region_help_text)
        safe_update(self._region_legend_container)
        if self._selected_region_coord is not None:
            data = self._map_service.get_all_data()
            size = data.get(self._selected_region_coord)
            if size is not None:
                self._on_region_selected(self._selected_region_coord, size, None)

    def _change_region_detail_level(self, e: ft.ControlEvent) -> None:
        # v1 map is region-level only; keep method for API compatibility
        level = getattr(e.control, "value", None) or "region"
        if self._map_view is not None and hasattr(self._map_view, "set_detail_level"):
            self._map_view.set_detail_level(level)

    def _get_region_display_help(self, mode: str) -> str:
        return {
            "topview": self.app.translate(
                "map.help_topview",
                "地表瓦片按视口 LOD 渐进加载；滚轮缩放，拖拽平移。",
            ),
            "activity": self.app.translate(
                "map.help_activity",
                "区域模式显示 MCA 覆盖范围，适合检查缺失区域。",
            ),
            "biome": self.app.translate(
                "map.help_biome",
                "按区域采样主要群系；元数据仅为可见区域按需加载。",
            ),
            "structure": self.app.translate(
                "map.help_structure",
                "按区域采样生成结构；颜色表示主要结构和引用数量。",
            ),
        }.get(mode, self.app.translate("map.help", REGION_DISPLAY_HELP))

    def _map_zoom_in(self) -> None:
        map_view = self._map_view
        if map_view is not None and hasattr(map_view, "zoom_in"):
            map_view.zoom_in()

    def _map_zoom_out(self) -> None:
        map_view = self._map_view
        if map_view is not None and hasattr(map_view, "zoom_out"):
            map_view.zoom_out()

    def _map_reset_view(self) -> None:
        map_view = self._map_view
        if map_view is not None and hasattr(map_view, "reset_view"):
            map_view.reset_view()

    def _toggle_map_coordinates(self) -> None:
        map_view = self._map_view
        if map_view is not None and hasattr(map_view, "toggle_coordinates"):
            enabled = map_view.toggle_coordinates()
            controller = getattr(self, "_map_controller", None)
            if controller is not None:
                controller.toggle_layer("coordinates", enabled)
            self._set_map_toggle_button(
                self._map_coord_btn,
                enabled,
                self.app.translate("map.hide_coordinates", "隐藏坐标"),
                self.app.translate("map.show_coordinates", "显示坐标"),
            )
            safe_update(self._map_coord_btn)

    def _toggle_map_empty_regions(self) -> None:
        map_view = self._map_view
        if map_view is not None and hasattr(map_view, "toggle_empty_regions"):
            enabled = map_view.toggle_empty_regions()
            controller = getattr(self, "_map_controller", None)
            if controller is not None:
                controller.toggle_layer("empty", enabled)
            self._set_map_toggle_button(
                self._map_empty_btn,
                enabled,
                self.app.translate("map.hide_empty", "隐藏空区域"),
                self.app.translate("map.show_empty", "显示空区域"),
            )
            safe_update(self._map_empty_btn)

    @staticmethod
    def _set_map_toggle_button(
        button: Any,
        enabled: bool,
        enabled_label: str,
        disabled_label: str,
    ) -> None:
        label = enabled_label if enabled else disabled_label
        if hasattr(button, "set_text"):
            button.set_text(label)
            return
        button.selected = enabled
        button.tooltip = label

    def _toggle_map_markers(self) -> None:
        map_view = self._map_view
        if map_view is None or not hasattr(map_view, "toggle_markers"):
            return
        enabled = bool(map_view.toggle_markers())
        controller = getattr(self, "_map_controller", None)
        if controller is not None:
            controller.toggle_layer("markers", enabled)
        self._set_map_toggle_button(
            self._map_marker_btn,
            enabled,
            self.app.translate("map.hide_markers", "隐藏标记"),
            self.app.translate("map.show_markers", "显示标记"),
        )
        safe_update(self._map_marker_btn)

    def _search_map(self, _event: Any = None) -> None:
        controller = getattr(self, "_map_controller", None)
        field = getattr(self, "_map_search_field", None)
        if controller is None or field is None:
            return
        try:
            results = controller.search(field.value or "")
            result = results[0]
            field.error_text = None
            if self._map_view is not None:
                self._map_view.focus_block(result.x, result.z, target_scale=3.0)
            if result.marker_id is not None:
                marker = next(
                    (
                        item
                        for item in controller.markers()
                        if item.id == result.marker_id
                    ),
                    None,
                )
                if marker is not None:
                    self._on_map_marker_selected(marker)
            else:
                self._region_status_text.value = self.app.translate(
                    "map.located_block",
                    "定位到方块 X {x}, Z {z}",
                    x=result.x,
                    z=result.z,
                )
                self._region_status_text.color = THEME.accent_light
                safe_update(self._region_status_text)
            safe_update(field)
        except MapSearchError as exc:
            error_key, fallback = {
                "empty": ("map.search_empty", "搜索内容不能为空"),
                "invalid_format": (
                    "map.search_invalid_format",
                    "坐标格式无效，请输入 x,z、x y z、r.rx.rz 或 c.cx.cz",
                ),
                "not_found": (
                    "map.marker_not_found",
                    "未找到名称包含“{query}”的地图标记",
                ),
            }.get(exc.code, ("map.search_failed", "地图搜索失败"))
            field.error_text = self.app.translate(
                error_key,
                fallback,
                query=exc.query,
            )
            safe_update(field)
        except Exception as exc:
            self.app.handle_exception(
                exc,
                title=self.app.translate("map.search_failed", "地图搜索失败"),
            )

    def _on_map_marker_selected(self, marker: MapMarker) -> None:
        self._selected_marker_id = marker.id
        if self._map_view is not None and hasattr(self._map_view, "select_marker"):
            self._map_view.select_marker(marker.id)
        self._region_status_text.value = self.app.translate(
            "map.marker_details",
            "标记 {name}\nX {x}, Y {y}, Z {z}",
            name=marker.name,
            x=marker.x,
            y=marker.y,
            z=marker.z,
        )
        self._region_status_text.color = marker.color
        if hasattr(self, "_map_delete_marker_btn"):
            self._map_delete_marker_btn.disabled = self._marker_busy
            safe_update(self._map_delete_marker_btn)
        self._refresh_marker_list()
        safe_update(self._region_status_text)

    def _refresh_map_markers(self) -> None:
        controller = getattr(self, "_map_controller", None)
        markers = controller.markers() if controller is not None else []
        marker_ids = {marker.id for marker in markers}
        selected_marker_id = getattr(self, "_selected_marker_id", None)
        if selected_marker_id not in marker_ids:
            self._selected_marker_id = None
            if hasattr(self, "_map_delete_marker_btn"):
                self._map_delete_marker_btn.disabled = True
                safe_update(self._map_delete_marker_btn)
        elif hasattr(self, "_map_delete_marker_btn"):
            self._map_delete_marker_btn.disabled = self._marker_busy
            safe_update(self._map_delete_marker_btn)
        if self._map_view is not None and hasattr(self._map_view, "set_markers"):
            self._map_view.set_markers(markers)
        self._refresh_marker_list(markers)

    def _request_map_marker_load(self) -> None:
        """提交当前世界/维度标记加载，不在 UI 回调读取 JSON。"""
        controller = getattr(self, "_map_controller", None)
        if controller is None or controller.world_path is None:
            return
        self._set_map_marker_busy(True)
        try:
            controller.submit_load_markers(
                self._finish_map_marker_load,
                self._handle_map_marker_error,
            )
        except (RuntimeClosedError, TaskQueueFullError, RuntimeError) as error:
            self._handle_map_marker_error(error)

    def _finish_map_marker_load(self) -> None:
        self._set_map_marker_busy(False)
        if hasattr(self, "_map_marker_list"):
            self._refresh_map_markers()

    def _handle_map_marker_error(self, error: Exception) -> None:
        self._set_map_marker_busy(False)
        self.app.handle_exception(
            error,
            title=self.app.translate(
                "map.marker_operation_failed",
                "地图标记操作失败",
            ),
        )

    def _set_map_marker_busy(self, busy: bool) -> None:
        self._marker_busy = busy
        add_button = getattr(self, "_map_add_marker_btn", None)
        if add_button is not None:
            add_button.disabled = busy
            safe_update(add_button)
        delete_button = getattr(self, "_map_delete_marker_btn", None)
        if delete_button is not None:
            delete_button.disabled = busy or not getattr(
                self,
                "_selected_marker_id",
                None,
            )
            safe_update(delete_button)

    def _refresh_marker_list(
        self,
        markers: Optional[list[MapMarker]] = None,
    ) -> None:
        if not hasattr(self, "_map_marker_list"):
            return
        controller = getattr(self, "_map_controller", None)
        if markers is None:
            marker_values = controller.markers() if controller is not None else []
        else:
            marker_values = markers
        rows: list[ft.Control] = [
            self._build_marker_list_row(marker)
            for marker in marker_values
        ]
        if not rows:
            rows.append(
                ft.Text(
                    self.app.translate("map.no_markers", "当前维度没有标记"),
                    size=12,
                    color=THEME.text_muted,
                )
            )
        self._map_marker_list.controls = rows
        self._map_marker_count_text.value = self.app.translate(
            "map.marker_count",
            "{count} 个标记",
            count=len(marker_values),
        )
        safe_update(self._map_marker_list)
        safe_update(self._map_marker_count_text)

    def _build_marker_list_row(self, marker: MapMarker) -> ft.Container:
        selected = marker.id == getattr(self, "_selected_marker_id", None)
        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(
                        ft.Icons.LOCATION_ON,
                        size=15,
                        color=marker.color,
                    ),
                    ft.Column(
                        [
                            ft.Text(
                                marker.name,
                                size=11,
                                weight=(
                                    ft.FontWeight.BOLD if selected else None
                                ),
                                color=THEME.text_primary,
                                no_wrap=True,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                            ft.Text(
                                f"X {marker.x} · Z {marker.z}",
                                size=9,
                                color=THEME.text_muted,
                            ),
                        ],
                        spacing=0,
                        expand=True,
                    ),
                ],
                spacing=5,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding(left=6, right=6, top=4, bottom=4),
            bgcolor=THEME.bg_card_hover if selected else None,
            border_radius=4,
            on_click=lambda _event, item=marker: self._focus_map_marker(item),
        )

    def _focus_map_marker(self, marker: MapMarker) -> None:
        self._on_map_marker_selected(marker)
        if self._map_view is not None:
            self._map_view.focus_block(marker.x, marker.z, target_scale=3.0)

    def _show_add_marker_dialog(self, _event: Any = None) -> None:
        controller = getattr(self, "_map_controller", None)
        if self.world_session is None or controller is None:
            self.app.warn_dialog(
                self.app.translate("map.notice", "提示"),
                self.app.translate("map.select_save_first", "请先设置当前存档。"),
            )
            return
        fields = self._build_add_marker_fields()
        error_text = ft.Text(size=11, color=THEME.error)
        dialog_holder: dict[str, Any] = {}
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(
                self.app.translate("map.add_marker_title", "添加地图标记")
            ),
            content=self._build_add_marker_dialog_content(fields, error_text),
            actions=self._build_add_marker_dialog_actions(
                controller,
                fields,
                error_text,
                dialog_holder,
            ),
        )
        dialog_holder["dialog"] = dialog
        self.app.page.show_dialog(dialog)

    def _build_add_marker_dialog_content(
        self,
        fields: dict[str, Any],
        error_text: ft.Text,
    ) -> ft.Column:
        return ft.Column(
            [
                fields["name_field"],
                ft.Row(
                    [
                        fields["x_field"],
                        fields["y_field"],
                        fields["z_field"],
                    ],
                    spacing=6,
                ),
                fields["color_field"],
                error_text,
            ],
            spacing=8,
            tight=True,
        )

    def _build_add_marker_dialog_actions(
        self,
        controller: Any,
        fields: dict[str, Any],
        error_text: ft.Text,
        dialog_holder: dict[str, Any],
    ) -> list[ft.Control]:
        def close(_click: Any = None) -> None:
            dialog = dialog_holder.get("dialog")
            if dialog is not None:
                dialog.open = False
            self.app.page.update()

        def save(_click: Any = None) -> None:
            if getattr(self, "_marker_busy", False):
                return
            try:
                self._set_map_marker_busy(True)
                controller.submit_upsert_marker(
                    fields["name_field"].value or "",
                    int((fields["x_field"].value or "0").strip()),
                    int((fields["z_field"].value or "0").strip()),
                    y=int((fields["y_field"].value or "64").strip()),
                    color=fields["color_field"].value or "#FFD54F",
                    on_complete=lambda marker: self._finish_add_map_marker(
                        marker,
                        close,
                    ),
                    on_error=lambda error: self._show_add_marker_error(
                        error,
                        error_text,
                    ),
                )
            except (TypeError, ValueError) as exc:
                self._set_map_marker_busy(False)
                error_text.value = str(exc)
                safe_update(error_text)
            except (RuntimeClosedError, TaskQueueFullError, RuntimeError) as exc:
                self._show_add_marker_error(exc, error_text)

        return [
            ft.TextButton(
                self.app.translate("map.add", "添加"),
                icon=ft.Icons.ADD_LOCATION_ALT,
                on_click=save,
            ),
            ft.TextButton(
                self.app.translate("map.cancel", "取消"),
                on_click=close,
            ),
        ]

    def _finish_add_map_marker(
        self,
        marker: MapMarker,
        close_dialog: Callable[[], None],
    ) -> None:
        self._set_map_marker_busy(False)
        close_dialog()
        self._refresh_map_markers()
        self._focus_map_marker(marker)

    def _show_add_marker_error(
        self,
        error: Exception,
        error_text: ft.Text,
    ) -> None:
        self._set_map_marker_busy(False)
        error_text.value = str(error)
        safe_update(error_text)

    def _build_add_marker_fields(self) -> dict[str, Any]:
        block_x, block_z = self._default_marker_coordinates()
        return {
            "name_field": ft.TextField(
                label=self.app.translate("map.marker_name", "名称"),
                autofocus=True,
                width=300,
            ),
            "x_field": ft.TextField(label="X", value=str(block_x), width=100),
            "y_field": ft.TextField(label="Y", value="64", width=100),
            "z_field": ft.TextField(label="Z", value=str(block_z), width=100),
            "color_field": ft.Dropdown(
                label=self.app.translate("map.marker_color", "颜色"),
                value="#FFD54F",
                width=180,
                options=[
                    ft.dropdown.Option(
                        "#FFD54F",
                        self.app.translate("map.color_gold", "金色"),
                    ),
                    ft.dropdown.Option(
                        "#55FF55",
                        self.app.translate("map.color_green", "绿色"),
                    ),
                    ft.dropdown.Option(
                        "#55AAFF",
                        self.app.translate("map.color_blue", "蓝色"),
                    ),
                    ft.dropdown.Option(
                        "#FF6B6B",
                        self.app.translate("map.color_red", "红色"),
                    ),
                    ft.dropdown.Option(
                        "#FFFFFF",
                        self.app.translate("map.color_white", "白色"),
                    ),
                ],
            ),
        }

    def _default_marker_coordinates(self) -> Tuple[int, int]:
        if self._map_view is not None:
            chunk = self._map_view.get_selected_chunk()
            if chunk is not None:
                return chunk[0] * 16 + 8, chunk[1] * 16 + 8
            selected = self._map_view.get_selected_cell()
            if selected is not None:
                return selected[0] * 512 + 256, selected[1] * 512 + 256
            return self._map_view.get_center_block()
        return (0, 0)

    def _delete_selected_marker(self, _event: Any = None) -> None:
        marker_id = getattr(self, "_selected_marker_id", None)
        controller = getattr(self, "_map_controller", None)
        if (
            not marker_id
            or controller is None
            or getattr(self, "_marker_busy", False)
        ):
            return
        try:
            self._set_map_marker_busy(True)
            controller.submit_delete_marker(
                marker_id,
                on_complete=self._finish_delete_map_marker,
                on_error=self._handle_delete_map_marker_error,
            )
        except (
            KeyError,
            RuntimeClosedError,
            TaskQueueFullError,
            RuntimeError,
        ) as error:
            self._handle_delete_map_marker_error(error)

    def _finish_delete_map_marker(self, deleted: bool) -> None:
        self._set_map_marker_busy(False)
        self._refresh_map_markers()
        if not deleted:
            return
        self._selected_marker_id = None
        self._map_delete_marker_btn.disabled = True
        self._region_status_text.value = self.app.translate(
            "map.marker_deleted",
            "地图标记已删除",
        )
        self._region_status_text.color = THEME.text_secondary
        safe_update(self._region_status_text)
        safe_update(self._map_delete_marker_btn)

    def _handle_delete_map_marker_error(self, error: Exception) -> None:
        self._set_map_marker_busy(False)
        self.app.handle_exception(
            error,
            title=self.app.translate(
                "map.delete_marker_failed",
                "删除地图标记失败",
            ),
        )

    def _on_region_selected(self,
                            coord: Optional[Tuple[int, int]],
                            size: Optional[int],
                            detail: Optional[Dict[str, Any]] = None) -> None:
        stats = self._map_service.get_statistics()
        if coord is None or size is None:
            self._selected_region_coord = None
            total = stats.get("total_regions", 0)
            self._region_stats_text.value = f"已生成区域: {total} 个"
            self._region_stats_text.color = THEME.text_primary
            self._region_status_text.value = "扫描完成：点击方块查看详情"
            self._region_status_text.color = THEME.text_secondary
            safe_update(self._region_stats_text)
            safe_update(self._region_status_text)
            return

        self._selected_region_coord = coord
        self._region_status_text.value = format_region_selection(coord, detail)
        self._region_status_text.color = THEME.accent_light
        safe_update(self._region_status_text)

    def _delete_selected_region(self, e: Any) -> None:
        """校验内存选择，并把区域删除提交到共享 I/O 通道。"""
        try:
            if self.world_session is None or self._selected_region_coord is None:
                self.app.warn_dialog("提示", "请先在区域地图中选择一个区域。")
                return
            region_dir = self._get_current_region_dir()
            if region_dir is None:
                self.app.warn_dialog("提示", "当前维度没有可用的 region 目录。")
                return
            coord = self._selected_region_coord
            region_path = region_dir / f"r.{coord[0]}.{coord[1]}.mca"
            world_path = self.world_session.world_path
            request = RegionDeleteRequest(
                world_path=world_path,
                region_path=region_path,
                coord=coord,
                generation=self._world_load_generation,
            )
            self._region_delete_controller.start(
                request,
                lambda outcome: run_on_ui(
                    self.app.page,
                    self._apply_region_delete_outcome,
                    outcome,
                ),
            )
        except RegionDeleteBusyError:
            self.app.warn_dialog(
                self._t("region_delete.busy_title", "删除进行中"),
                self._t(
                    "region_delete.busy_message",
                    "已有区域删除正在执行，请等待当前操作完成。",
                ),
            )
        except (TaskQueueFullError, RuntimeClosedError):
            self.app.warn_dialog(
                self._t("region_delete.queue_full_title", "后台任务繁忙"),
                self._t(
                    "region_delete.queue_full_message",
                    "后台 I/O 队列已满，请稍后重试。",
                ),
            )
        except Exception as ex:
            self.app.handle_exception(ex, title="删除区域失败")

    def _apply_region_delete_outcome(
        self,
        outcome: RegionDeleteOutcome,
    ) -> None:
        """在 UI 线程投影区域删除终态，并拒绝过期结果。"""
        request = outcome.request
        session = self.world_session
        if (
            request.generation != self._world_load_generation
            or session is None
            or session.world_path.resolve() != request.world_path.resolve()
        ):
            self.app.log(
                f"丢弃过期区域删除回调: {request.region_path}",
                "INFO",
            )
            return
        if outcome.status is RegionDeleteStatus.CANCELLED:
            self.app.warn_dialog(
                self._t("region_delete.cancelled_title", "删除已取消"),
                self._t(
                    "region_delete.cancelled_message",
                    "区域删除已在安全检查点取消，原存档保持不变。",
                ),
            )
            return
        if outcome.status is RegionDeleteStatus.FAILED:
            error = outcome.error or RuntimeError("区域删除失败")
            self.app.handle_exception(error, title="区域删除失败")
            return
        result = outcome.result
        if result is None or not result.value:
            self.app.warn_dialog("失败", "区域删除失败，请查看日志。")
            return
        self.app.info_dialog(
            "成功",
            f"已删除区域 {request.coord}，游戏下次进入会重新生成。"
            f"安全备份: {result.backup.backup_path.name}",
        )
        self._selected_region_coord = None
        # 事务已使共享索引失效；异步重载会话，避免继续使用旧维度快照。
        self._load_world(request.world_path)

    def _fill_selected_region_for_nbt(self, e: Any = None) -> None:
        try:
            if self.world_session is None or self._selected_region_coord is None:
                self.app.warn_dialog("提示", "请先在区域地图中选择一个区域。")
                return
            region_dir = self._get_current_region_dir()
            if region_dir is None:
                self.app.warn_dialog("提示", "当前维度没有可用的 region 目录。")
                return
            coord = self._selected_region_coord
            region_path = region_dir / f"r.{coord[0]}.{coord[1]}.mca"
            if not region_path.exists():
                self.app.warn_dialog("提示", f"区域文件不存在: {region_path.name}")
                return
            relative_path = region_path.resolve().relative_to(
                self.world_session.world_path.resolve())
            self._region_file_field.value = str(relative_path).replace("\\", "/")
            self._chunk_x_field.value = "0"
            self._chunk_z_field.value = "0"
            safe_update(self._region_file_field)
            safe_update(self._chunk_x_field)
            safe_update(self._chunk_z_field)
            self._switch_tab(5)  # NBT 标签页索引
        except Exception as ex:
            self.app.handle_exception(ex, title="填入区域文件失败")

    def _fill_chunk_from_world_coords(self, e: Any = None) -> bool:
        try:
            if not self.world_session:
                self.app.warn_dialog("提示", "请先通过侧边栏设置当前存档。")
                return False
            region_dir = self._get_current_region_dir()
            if region_dir is None:
                self.app.warn_dialog("提示", "当前维度没有可用的 region 目录。")
                return False
            world_x = int(float((self._world_x_field.value or "0").strip()))
            world_z = int(float((self._world_z_field.value or "0").strip()))
            (
                region_x,
                region_z,
                local_chunk_x,
                local_chunk_z,
            ) = self._world_coords_to_region_chunk(world_x, world_z)
            region_path = region_dir / f"r.{region_x}.{region_z}.mca"
            relative_path = region_path.resolve().relative_to(
                self.world_session.world_path.resolve())
            self._region_file_field.value = str(relative_path).replace("\\", "/")
            self._chunk_x_field.value = str(local_chunk_x)
            self._chunk_z_field.value = str(local_chunk_z)
            safe_update(self._region_file_field)
            safe_update(self._chunk_x_field)
            safe_update(self._chunk_z_field)
            if not region_path.exists():
                self.app.warn_dialog(
                    "提示", f"已填入坐标，但区域文件不存在: r.{region_x}.{region_z}.mca")
                return False
            return True
        except ValueError:
            self.app.warn_dialog("提示", "世界坐标必须是数字。")
            return False
        except Exception as ex:
            self.app.handle_exception(ex, title="填入世界坐标失败")
            return False

    def _load_chunk_from_world_coords(self, e: Any = None) -> None:
        if self._fill_chunk_from_world_coords(e):
            self._load_chunk_nbt(e)

    def _get_current_region_dir(self) -> Optional[Path]:
        region_dir = self._dimension_region_dirs.get(self._current_dimension)
        return Path(region_dir) if region_dir else None

    def _refresh_map(self) -> None:
        try:
            if not self.world_session:
                return
            if not hasattr(self, "_region_stats_text") or self._map_view is None:
                return
            self._selected_region_coord = None
            region_dir_str = self._dimension_region_dirs.get(self._current_dimension)
            if not region_dir_str:
                self._region_stats_text.value = "警告：未找到当前维度的 region 目录"
                self._region_stats_text.color = THEME.warning
                safe_update(self._region_stats_text)
                return
            region_dir = Path(region_dir_str)
            if not region_dir.exists():
                self._region_stats_text.value = "警告：region 目录不存在"
                self._region_stats_text.color = THEME.warning
                safe_update(self._region_stats_text)
                return
            self._map_service.clear_data()
            self._region_stats_text.value = "正在扫描..."
            self._region_stats_text.color = THEME.accent
            safe_update(self._region_stats_text)
            map_view = self._map_view
            if map_view is not None and hasattr(map_view, "start_scan"):
                map_view.start_scan(str(region_dir))
                self._refresh_map_markers()
            else:
                self.app.warn_dialog("提示", "当前区域地图组件不支持后台扫描")
        except Exception as e:
            self.app.handle_exception(e, title="刷新区域地图失败")

    def _update_dimension_list(self) -> None:
        try:
            if not self.world_session:
                return
            dimensions = self.world_session.get_dimensions()
            controller = getattr(self, "_map_controller", None)
            if controller is not None and controller.world_path is None:
                controller.bind_world(self.world_session.world_path, dimensions)
                self._request_map_marker_load()
            options = self._build_dimension_options(dimensions)
            self._select_current_dimension(options, controller)
            self._update_dimension_dropdown(options)
            self._restore_controller_map_state(controller)
        except Exception as e:
            self.app.handle_exception(e, title="扫描维度失败")

    def _build_dimension_options(
        self, dimensions: list[DimensionInfo]
    ) -> list[ft.dropdown.Option]:
        self._dimension_region_dirs.clear()
        options: list[ft.dropdown.Option] = []
        for dimension in dimensions:
            dimension_id = str(dimension["id"])
            self._dimension_region_dirs[dimension_id] = str(dimension["region_dir"])
            options.append(ft.dropdown.Option(dimension_id, str(dimension["name"])))
        return options

    def _select_current_dimension(
        self, options: list[ft.dropdown.Option], controller: Optional[MapController]
    ) -> None:
        if not options:
            self._current_dimension = ""
            return
        controller_dimension = (
            controller.snapshot.dimension_id if controller is not None else None
        )
        if controller_dimension in self._dimension_region_dirs:
            self._current_dimension = controller_dimension
        elif self._current_dimension not in self._dimension_region_dirs:
            self._current_dimension = options[0].key or ""

    def _update_dimension_dropdown(self, options: list[ft.dropdown.Option]) -> None:
        if hasattr(self, "_dimension_dropdown"):
            self._dimension_dropdown.options = options
            self._dimension_dropdown.value = self._current_dimension
            safe_update(self._dimension_dropdown)

    def _restore_controller_map_state(self, controller: Optional[MapController]) -> None:
        if (
            controller is not None
            and self._current_dimension == controller.snapshot.dimension_id
            and hasattr(self, "_map_coord_btn")
        ):
            self._apply_map_state(controller.snapshot)

    def _on_dimension_changed(self, e: Any) -> None:
        try:
            new_dim = e.control.value
            if new_dim == self._current_dimension:
                return
            controller = getattr(self, "_map_controller", None)
            if controller is not None and self._map_view is not None:
                center_x, center_z = self._map_view.get_center_block()
                controller.update_camera(
                    center_x,
                    center_z,
                    self._map_view.get_camera_scale(),
                )
                controller.switch_dimension(new_dim)
                state = controller.snapshot
            else:
                state = None
            self._current_dimension = new_dim
            self._selected_marker_id = None
            self._map_delete_marker_btn.disabled = True
            safe_update(self._map_delete_marker_btn)
            self._refresh_map()
            self._request_map_marker_load()
            if state is not None and self._map_view is not None:
                self._apply_map_state(state)
                self._map_view.focus_block(
                    int(state.center_x),
                    int(state.center_z),
                    animate=False,
                    target_scale=state.scale,
                )
        except Exception as ex:
            self.app.handle_exception(ex, title="切换维度失败")

    def _apply_map_state(
        self,
        state: MapViewState | MapViewStateSnapshot,
    ) -> None:
        """Synchronize view controls with the controller's dimension snapshot."""
        from app.presenters.map_viewport_state import decide_map_rebuild

        previous = getattr(self, "_map_viewport_snapshot", None)
        decision = decide_map_rebuild(previous, state)
        self._map_viewport_snapshot = decision.snapshot
        self._region_display_mode = state.style
        self._region_display_mode_dropdown.value = state.style
        if self._map_view is not None:
            # Always sync mode/layers; rebuild decision is recorded for
            # consumers that want to skip expensive canvas work.
            self._map_view.set_display_mode(state.style)
            self._map_view.apply_layer_state(state.layers)
            self._last_map_rebuild_reason = decision.reason
        self._set_map_toggle_button(
            self._map_coord_btn,
            state.layers.show_coordinates,
            self.app.translate("map.hide_coordinates", "隐藏坐标"),
            self.app.translate("map.show_coordinates", "显示坐标"),
        )
        self._set_map_toggle_button(
            self._map_empty_btn,
            state.layers.show_empty_regions,
            self.app.translate("map.hide_empty", "隐藏空区域"),
            self.app.translate("map.show_empty", "显示空区域"),
        )
        self._set_map_toggle_button(
            self._map_marker_btn,
            state.layers.show_markers,
            self.app.translate("map.hide_markers", "隐藏标记"),
            self.app.translate("map.show_markers", "显示标记"),
        )
        safe_update(self._region_display_mode_dropdown)
        safe_update(self._map_coord_btn)
        safe_update(self._map_empty_btn)
        safe_update(self._map_marker_btn)

    def _update_region_stats(self) -> None:
        stats = self._map_service.get_statistics()
        total = stats.get("total_regions", 0)
        self._region_stats_text.value = f"已生成区域: {total} 个"
        self._region_stats_text.color = THEME.text_primary
        safe_update(self._region_stats_text)
