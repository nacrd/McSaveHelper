"""Region map tab mixin for ExplorerView.

Hosts the simplified map display (McaMapView) for browsing MCA regions.
"""
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import flet as ft

from app.ui.theme import THEME
from app.ui.views.explorer.utils import safe_update
from app.ui.views.explorer.map import McaMapView
from app.ui.views.explorer.map.fullscreen import MapFullscreenController
from app.ui.views.explorer.mixin_context import ExplorerMixinHost
from app.ui.views.explorer.region_tab_chrome import (
    REGION_DISPLAY_HELP,
    REGION_LEGEND,
    build_map_fallback,
    build_region_legend_content,
    build_region_tab_chrome,
)
from core.mca.region_selection import format_region_selection


class RegionTabMixin(ExplorerMixinHost):
    """Build and handle the Explorer region / map tab."""

    def _build_region_tab(self) -> None:
        try:
            self._map_view = McaMapView(
                map_service=self._map_service,
                on_selection_changed=self._on_region_selected,
                width=900,
                height=560,
            )
            map_view = self._map_view
        except Exception:
            self._map_view = None
            map_view = build_map_fallback()

        chrome = build_region_tab_chrome(
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
        )
        self._region_display_mode = "topview"
        self._dimension_dropdown = chrome.dimension_dropdown
        self._region_display_mode_dropdown = chrome.display_mode_dropdown
        self._map_coord_btn = chrome.coord_button
        self._map_empty_btn = chrome.empty_button
        self._map_fullscreen_btn = chrome.fullscreen_button
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
        self._map_fullscreen_controller = (
            MapFullscreenController(
                page=self.app.page,
                map_view=self._map_view,
                inline_host=self._map_host,
                side_panel=self._region_side_panel,
                set_toggle_label=self._set_map_fullscreen_label,
                refresh=self._refresh_map,
                zoom_in=self._map_zoom_in,
                zoom_out=self._map_zoom_out,
                reset=self._map_reset_view,
            )
            if self._map_view is not None
            else None
        )

    def _toggle_map_fullscreen(self) -> None:
        if self._map_fullscreen_controller is not None:
            self._map_fullscreen_controller.toggle()

    def _set_map_fullscreen_label(self, label: str) -> None:
        self._map_fullscreen_btn.set_text(label)
        safe_update(self._map_fullscreen_btn)

    def _dispose_region_tab(self) -> None:
        controller = getattr(self, "_map_fullscreen_controller", None)
        if controller is not None:
            controller.dispose()

    def _enter_map_fullscreen(self) -> None:
        if self._map_fullscreen_controller is not None:
            self._map_fullscreen_controller.enter()

    def _exit_map_fullscreen(self) -> None:
        if self._map_fullscreen_controller is not None:
            self._map_fullscreen_controller.exit()

    def _create_region_legend_content(self) -> ft.Column:
        return build_region_legend_content()

    def _get_region_display_legend(
            self) -> tuple[str, list[tuple[str, str, str]]]:
        return "🗺️ 俯视图例", list(REGION_LEGEND)

    def _change_region_display_mode(self) -> None:
        mode = self._region_display_mode_dropdown.value or "topview"
        self._region_display_mode = mode
        if self._map_view is not None and hasattr(self._map_view, "set_display_mode"):
            self._map_view.set_display_mode(mode)
        self._region_help_text.value = self._get_region_display_help(mode)
        self._region_legend_container.content = self._create_region_legend_content()
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
        del mode
        return REGION_DISPLAY_HELP

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
            self._map_coord_btn.set_text("隐藏坐标" if enabled else "显示坐标")
            safe_update(self._map_coord_btn)

    def _toggle_map_empty_regions(self) -> None:
        map_view = self._map_view
        if map_view is not None and hasattr(map_view, "toggle_empty_regions"):
            enabled = map_view.toggle_empty_regions()
            self._map_empty_btn.set_text("隐藏空格" if enabled else "显示空格")
            safe_update(self._map_empty_btn)

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
            self._region_status_text.value = "✅ 扫描完成，点击方块查看详情"
            self._region_status_text.color = THEME.text_secondary
            safe_update(self._region_stats_text)
            safe_update(self._region_status_text)
            return

        self._selected_region_coord = coord
        self._region_status_text.value = format_region_selection(coord, detail)
        self._region_status_text.color = THEME.accent_light
        safe_update(self._region_status_text)

    def _delete_selected_region(self, e: Any) -> None:
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
            from app.services.region_editor_service import get_region_editor_service
            service = get_region_editor_service(log=self.app.log)
            if service.reset_region(region_path, backup=True):
                self.app.info_dialog(
                    "成功", f"已删除区域 {coord}，游戏下次进入会重新生成。备份文件保留为 .bak。")
                self._selected_region_coord = None
                self._refresh_map()
            else:
                self.app.warn_dialog("失败", "区域删除失败，请查看日志。")
        except Exception as ex:
            self.app.handle_exception(ex, title="删除区域失败")

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
                self._region_stats_text.value = "⚠️ 未找到当前维度的 region 目录"
                self._region_stats_text.color = THEME.warning
                safe_update(self._region_stats_text)
                return
            region_dir = Path(region_dir_str)
            if not region_dir.exists():
                self._region_stats_text.value = "⚠️ region 目录不存在"
                self._region_stats_text.color = THEME.warning
                safe_update(self._region_stats_text)
                return
            self._map_service.clear_data()
            self._region_stats_text.value = "🔄 正在扫描..."
            self._region_stats_text.color = THEME.accent
            safe_update(self._region_stats_text)
            map_view = self._map_view
            if map_view is not None and hasattr(map_view, "start_scan"):
                map_view.start_scan(str(region_dir))
            else:
                self.app.warn_dialog("提示", "当前区域地图组件不支持后台扫描")
        except Exception as e:
            self.app.handle_exception(e, title="刷新区域地图失败")

    def _update_dimension_list(self) -> None:
        try:
            if not self.world_session:
                return
            dimensions = self.world_session.get_dimensions()
            self._dimension_region_dirs.clear()
            options = []
            for dim in dimensions:
                dim_id = dim["id"]
                dim_name = dim["name"]
                region_dir = dim["region_dir"]
                self._dimension_region_dirs[dim_id] = region_dir
                options.append(ft.dropdown.Option(dim_id, dim_name))
            if options:
                if self._current_dimension not in self._dimension_region_dirs:
                    self._current_dimension = options[0].key
            else:
                self._current_dimension = ""
            if hasattr(self, "_dimension_dropdown"):
                self._dimension_dropdown.options = options
                self._dimension_dropdown.value = self._current_dimension
                safe_update(self._dimension_dropdown)
        except Exception as e:
            self.app.handle_exception(e, title="扫描维度失败")

    def _on_dimension_changed(self, e: Any) -> None:
        try:
            new_dim = e.control.value
            if new_dim == self._current_dimension:
                return
            self._current_dimension = new_dim
            self._refresh_map()
        except Exception as ex:
            self.app.handle_exception(ex, title="切换维度失败")

    def _update_region_stats(self) -> None:
        stats = self._map_service.get_statistics()
        total = stats.get("total_regions", 0)
        self._region_stats_text.value = f"已生成区域: {total} 个"
        self._region_stats_text.color = THEME.text_primary
        safe_update(self._region_stats_text)
