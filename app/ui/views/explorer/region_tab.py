"""Region map tab mixin for ExplorerView.

Hosts the simplified map display (McaMapView) for browsing MCA regions.
"""
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import flet as ft

from app.ui.theme import THEME, mc_border
from app.ui.components.buttons import btn_primary, btn_ghost, btn_danger
from app.ui.components.cards import card
from app.ui.views.explorer.utils import safe_update
from app.ui.views.explorer.map import McaMapView


class RegionTabMixin:
    """Build and handle the Explorer region / map tab."""

    def _build_region_tab(self) -> None:
        self._dimension_dropdown = ft.Dropdown(
            options=[],
            on_select=self._on_dimension_changed,
            border_color=THEME.border_standard,
            text_size=13,
            width=180,
        )

        dimension_row = ft.Row([
            ft.Text("维度：", size=14, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
            self._dimension_dropdown,
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        try:
            self._map_view = McaMapView(
                map_service=self._map_service,
                on_selection_changed=self._on_region_selected,
                width=420,
                height=260,
            )
            map_view = self._map_view
        except Exception:
            self._map_view = None
            map_view = ft.Container(
                content=ft.Column([
                    ft.Icon(ft.Icons.WARNING, size=48, color="#FF9800"),
                    ft.Text("区域地图组件不可用", size=16, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
                    ft.Text("请升级 Flet 版本以启用区域地图功能", size=13, color=THEME.text_muted),
                ], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                padding=50,
                bgcolor=THEME.bg_card,
                border_radius=8,
            )

        self._region_help_text = ft.Text(
            "1 格 = 1 个 r.x.z.mca 区域文件（512×512 方块）。扫描后逐步加载方块俯视图。",
            size=11,
            color=THEME.text_muted,
            no_wrap=True,
            overflow=ft.TextOverflow.ELLIPSIS,
        )

        # Keep display-mode state for side-panel detail text.
        self._region_display_mode = "topview"
        self._region_display_mode_dropdown = ft.Dropdown(
            label="显示方式",
            value="topview",
            width=150,
            options=[
                ft.dropdown.Option("topview", "方块俯视"),
            ],
            on_select=self._change_region_display_mode,
            border_color=THEME.border_light,
            focused_border_color=THEME.accent,
            color=THEME.text_primary,
            bgcolor=THEME.bg_card,
        )

        self._map_coord_btn = btn_ghost(
            "隐藏坐标", width=112, on_click=lambda e: self._toggle_map_coordinates())
        self._map_empty_btn = btn_ghost(
            "显示空格", width=112, on_click=lambda e: self._toggle_map_empty_regions())

        self._region_stats_text = ft.Text(
            "等待设置当前存档...", size=12, color=THEME.text_muted)
        self._region_status_text = ft.Text(
            "👆 点击方块查看详情", size=13, color=THEME.text_secondary)

        action_row = ft.Column([
            ft.Row([
                btn_primary("🔄 刷新", width=100, on_click=lambda e: self._refresh_map()),
                btn_ghost("🔍 放大", width=90, on_click=lambda e: self._map_zoom_in()),
            ], spacing=8),
            ft.Row([
                btn_ghost("🔍 缩小", width=90, on_click=lambda e: self._map_zoom_out()),
                btn_ghost("🏠 重置", width=90, on_click=lambda e: self._map_reset_view()),
            ], spacing=8),
            ft.Row([
                btn_ghost("填入 NBT", width=112, on_click=self._fill_selected_region_for_nbt),
                btn_danger("删除区域", width=112, on_click=self._delete_selected_region),
            ], spacing=8),
        ], spacing=8)

        view_option_row = ft.Row(
            [self._map_coord_btn, self._map_empty_btn], spacing=8)
        map_card = card(ft.Container(
            content=map_view,
            bgcolor=THEME.bg_secondary,
            border=mc_border(2),
            border_radius=0,
            padding=4,
            alignment=ft.alignment.Alignment(0, 0),
        ), padding=6)

        stats_card = card(ft.Column([
            ft.Text("📊 地图概况", size=13, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
            self._region_stats_text,
        ], spacing=6), padding=10)

        selection_card = card(ft.Column([
            ft.Text("👆 点击详情", size=13, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
            self._region_status_text,
        ], spacing=6), padding=10)

        self._region_legend_container = ft.Container(
            content=self._create_region_legend_content())
        legend = card(self._region_legend_container, padding=10)

        left_panel = ft.Container(
            content=ft.Column([
                card(ft.Row([
                    dimension_row,
                    self._region_display_mode_dropdown,
                    self._region_help_text,
                ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER), padding=8),
                map_card,
            ], spacing=8),
            expand=True,
        )
        self._region_left_panel = left_panel

        side_panel = ft.Container(
            content=ft.Column([
                selection_card,
                stats_card,
                legend,
                card(ft.Column([
                    ft.Text("⚙️ 显示选项", size=13, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
                    view_option_row,
                ], spacing=8), padding=10),
                card(ft.Column([
                    ft.Text("🛠️ 区域操作", size=13, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
                    action_row,
                ], spacing=8), padding=10),
            ], spacing=8, scroll=ft.ScrollMode.AUTO),
            height=320,
            width=360,
        )
        self._region_side_panel = side_panel

        self._tab_region.content = ft.Row([
            left_panel,
            side_panel,
        ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.START)

    def _create_region_legend_content(self) -> ft.Column:
        title, items = self._get_region_display_legend()
        legend_rows = []
        for color, item_title, desc in items:
            legend_rows.append(ft.Row([
                ft.Container(width=18, height=18, bgcolor=color, border_radius=2),
                ft.Text(item_title, size=11, color=THEME.text_primary, width=58),
                ft.Text(desc, size=10, color=THEME.text_muted),
            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER))
        return ft.Column([
            ft.Text(title, size=13, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
            *legend_rows,
        ], spacing=5)

    def _get_region_display_legend(
            self) -> tuple[str, list[tuple[str, str, str]]]:
        return "🗺️ 方块俯视图例", [
            ("#228B22", "草地/树叶", "地表植被"),
            ("#64A4DF", "水体", "海洋 / 河流"),
            ("#EED6AF", "沙地", "沙漠 / 沙滩"),
            ("#808080", "岩石", "石头 / 深板岩"),
            ("#4CAF50", "占位", "俯视尚未加载时的占位色"),
            ("#FFD54F", "选中", "当前选中的区域边框"),
        ]

    def _change_region_display_mode(self, e: ft.ControlEvent) -> None:
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
        return "按区域最高方块着色的俯视图；扫描时渐进加载，未加载前显示绿色占位。"

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
            self._region_stats_text.value = (
                f"🗺️ 已生成区域: {total} 个\n"
                f"点击地图上的方格查看区域坐标与文件信息。"
            )
            self._region_stats_text.color = THEME.text_primary
            self._region_status_text.value = "✅ 扫描完成，点击方块查看详情"
            self._region_status_text.color = THEME.text_secondary
            safe_update(self._region_stats_text)
            safe_update(self._region_status_text)
            return

        self._selected_region_coord = coord
        region_x, region_z = coord
        chunk_x0 = region_x * 32
        chunk_x1 = region_x * 32 + 31
        chunk_z0 = region_z * 32
        chunk_z1 = region_z * 32 + 31
        block_x0 = region_x * 512
        block_x1 = region_x * 512 + 511
        block_z0 = region_z * 512
        block_z1 = region_z * 512 + 511
        self._region_status_text.value = (
            f"✅ 已选择区域\n"
            f"   🧭 区域坐标: ({region_x}, {region_z})\n"
            f"   📄 文件: r.{region_x}.{region_z}.mca\n"
            f"   🧩 区块范围: X {chunk_x0} ~ {chunk_x1}, Z {chunk_z0} ~ {chunk_z1}\n"
            f"   🧱 方块范围: X {block_x0} ~ {block_x1}, Z {block_z0} ~ {block_z1}"
        )
        self._region_status_text.color = THEME.accent_light
        safe_update(self._region_status_text)

    def _delete_selected_region(self, e: Any) -> None:
        try:
            if not self.world_session or not self._selected_region_coord:
                self.app.warn_dialog("提示", "请先在区域地图中选择一个区域。")
                return
            region_dir = Path(
                self._dimension_region_dirs.get(self._current_dimension, ""))
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
            if not self.world_session or not self._selected_region_coord:
                self.app.warn_dialog("提示", "请先在区域地图中选择一个区域。")
                return
            region_dir = Path(
                self._dimension_region_dirs.get(self._current_dimension, ""))
            if not region_dir:
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
            region_dir = Path(
                self._dimension_region_dirs.get(self._current_dimension, ""))
            if not region_dir:
                self.app.warn_dialog("提示", "当前维度没有可用的 region 目录。")
                return False
            world_x = int(float((self._world_x_field.value or "0").strip()))
            world_z = int(float((self._world_z_field.value or "0").strip()))
            region_x, region_z, local_chunk_x, local_chunk_z = self._world_coords_to_region_chunk(
                world_x, world_z)
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
        self._region_stats_text.value = (
            f"🗺️ 已生成区域: {total} 个\n"
            f"点击地图上的方格查看区域坐标与文件信息。"
        )
        self._region_stats_text.color = THEME.text_primary
        safe_update(self._region_stats_text)
