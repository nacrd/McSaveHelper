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
                width=900,
                height=560,
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
            "1 格 = 1 个 r.x.z.mca · 俯视 128px · 点击区域局部放大",
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
            "隐藏坐标", width=88, on_click=lambda e: self._toggle_map_coordinates())
        self._map_empty_btn = btn_ghost(
            "显示空格", width=88, on_click=lambda e: self._toggle_map_empty_regions())
        self._map_fullscreen_btn = btn_ghost(
            "⛶ 全屏", width=88, on_click=lambda e: self._toggle_map_fullscreen())
        self._map_fullscreen = False
        self._map_fs_overlay: Optional[ft.Container] = None
        self._map_fs_body: Optional[ft.Container] = None
        self._map_inline_parent: Optional[ft.Container] = None
        self._map_pre_fs_size: Optional[Tuple[int, int]] = None

        self._region_stats_text = ft.Text(
            "等待设置当前存档...", size=11, color=THEME.text_muted)
        self._region_status_text = ft.Text(
            "👆 点击方块查看详情", size=12, color=THEME.text_secondary)

        action_row = ft.Row([
            btn_ghost("填入 NBT", width=100, on_click=self._fill_selected_region_for_nbt),
            btn_danger("删除区域", width=100, on_click=self._delete_selected_region),
        ], spacing=6)

        view_option_row = ft.Row(
            [self._map_coord_btn, self._map_empty_btn, self._map_fullscreen_btn],
            spacing=6,
        )
        toolbar = card(ft.Row([
            dimension_row,
            self._region_display_mode_dropdown,
            btn_primary("🔄 刷新", width=84, on_click=lambda e: self._refresh_map()),
            btn_ghost("🔍+", width=52, on_click=lambda e: self._map_zoom_in()),
            btn_ghost("🔍−", width=52, on_click=lambda e: self._map_zoom_out()),
            btn_ghost("🏠", width=52, on_click=lambda e: self._map_reset_view()),
            view_option_row,
            self._region_help_text,
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER, wrap=True), padding=8)
        self._region_toolbar = toolbar

        self._map_host = ft.Container(
            content=map_view,
            bgcolor=THEME.bg_secondary,
            border=mc_border(2),
            border_radius=0,
            padding=2,
            expand=True,
            alignment=ft.alignment.Alignment(0, 0),
        )
        map_card = card(self._map_host, padding=4)
        map_card.expand = True
        self._region_map_card = map_card

        stats_card = card(ft.Column([
            ft.Text("📊 概况", size=12, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
            self._region_stats_text,
        ], spacing=4), padding=8)

        selection_card = card(ft.Column([
            ft.Text("👆 选中", size=12, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
            self._region_status_text,
        ], spacing=4), padding=8)

        self._region_legend_container = ft.Container(
            content=self._create_region_legend_content())
        legend = card(self._region_legend_container, padding=8)

        left_panel = ft.Container(
            content=ft.Column([
                toolbar,
                map_card,
            ], spacing=6, expand=True),
            expand=True,
        )
        self._region_left_panel = left_panel

        # Compact side rail — no fixed height / no forced scroll
        side_panel = ft.Container(
            content=ft.Column([
                selection_card,
                stats_card,
                legend,
                card(ft.Column([
                    ft.Text("🛠️ 操作", size=12, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
                    action_row,
                ], spacing=6), padding=8),
            ], spacing=6),
            width=280,
            expand=False,
        )
        self._region_side_panel = side_panel

        self._region_layout = ft.Row(
            [left_panel, side_panel],
            spacing=10,
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        self._tab_region.content = self._region_layout
        self._tab_region.expand = True

    def _toggle_map_fullscreen(self) -> None:
        """App-wide fullscreen overlay for the map (covers sidebar + chrome)."""
        if getattr(self, "_map_fullscreen", False):
            self._exit_map_fullscreen()
        else:
            self._enter_map_fullscreen()

    def _page_window_size(self, page: ft.Page) -> Tuple[int, int]:
        """Best-effort full window content size for overlay layout."""
        w = 0
        h = 0
        try:
            w = int(getattr(page, "width", 0) or 0)
            h = int(getattr(page, "height", 0) or 0)
        except Exception:
            pass
        try:
            win = getattr(page, "window", None)
            if win is not None:
                ww = int(getattr(win, "width", 0) or 0)
                wh = int(getattr(win, "height", 0) or 0)
                w = max(w, ww)
                h = max(h, wh)
        except Exception:
            pass
        return max(800, w or 1100), max(600, h or 800)

    def _enter_map_fullscreen(self) -> None:
        map_view = getattr(self, "_map_view", None)
        page = getattr(getattr(self, "app", None), "page", None)
        host = getattr(self, "_map_host", None)
        if map_view is None or page is None or host is None:
            # Fallback: tab-only fullscreen
            self._map_fullscreen = True
            side = getattr(self, "_region_side_panel", None)
            if side is not None:
                side.visible = False
                try:
                    side.update()
                except Exception:
                    pass
            btn = getattr(self, "_map_fullscreen_btn", None)
            if btn is not None:
                btn.set_text("⛶ 退出")
                safe_update(btn)
            return

        # Avoid stacking multiple overlays
        if getattr(self, "_map_fs_overlay", None) is not None:
            return

        self._map_fullscreen = True
        self._map_inline_parent = host
        self._map_pre_fs_size = (
            int(map_view.width or 900),
            int(map_view.height or 560),
        )

        win_w, win_h = self._page_window_size(page)
        # Full-bleed overlay; tiny inset only for edge contrast
        pad = 0
        bar_h = 48
        map_w = max(400, win_w - pad * 2)
        map_h = max(300, win_h - bar_h - pad * 2)

        # Detach map from inline host
        host.content = ft.Container(
            content=ft.Text("地图全屏中…", size=13, color=THEME.text_muted),
            alignment=ft.alignment.Alignment(0, 0),
            expand=True,
            bgcolor=THEME.bg_secondary,
        )
        try:
            host.update()
        except Exception:
            pass

        exit_btn = btn_ghost("⛶ 退出全屏", width=120, on_click=lambda e: self._exit_map_fullscreen())
        zoom_in_btn = btn_ghost("🔍+", width=52, on_click=lambda e: self._map_zoom_in())
        zoom_out_btn = btn_ghost("🔍−", width=52, on_click=lambda e: self._map_zoom_out())
        reset_btn = btn_ghost("🏠", width=52, on_click=lambda e: self._map_reset_view())
        refresh_btn = btn_primary("🔄 刷新", width=84, on_click=lambda e: self._refresh_map())

        top_bar = ft.Container(
            content=ft.Row(
                [
                    ft.Text("🗺️ 区域地图 · 全屏", size=14, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
                    ft.Container(expand=True),
                    refresh_btn,
                    zoom_in_btn,
                    zoom_out_btn,
                    reset_btn,
                    exit_btn,
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding(left=12, right=12, top=8, bottom=8),
            height=bar_h,
            bgcolor=THEME.bg_card,
            border=mc_border(2),
        )

        # Force explicit pixel size so canvas really fills the window,
        # and re-fit/center the world to the new viewport.
        try:
            map_view.resize_map(map_w, map_h, refit=True)
        except TypeError:
            # Older signature fallback
            try:
                map_view.resize_map(map_w, map_h)
                if hasattr(map_view, "fit_to_view"):
                    map_view.fit_to_view()
            except Exception:
                pass
        except Exception:
            pass

        map_body = ft.Container(
            content=map_view,
            width=map_w,
            height=map_h,
            bgcolor=THEME.bg_secondary,
            padding=0,
            # Scale-in animation for enter
            scale=0.96,
            opacity=0.0,
            animate_scale=ft.Animation(220, ft.AnimationCurve.EASE_OUT_CUBIC),
            animate_opacity=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
        )
        self._map_fs_body = map_body

        # Absolute-positioned full-window overlay (page.overlay does not stretch expand alone)
        overlay = ft.Container(
            content=ft.Column(
                [top_bar, map_body],
                spacing=0,
                tight=True,
            ),
            left=0,
            top=0,
            width=win_w,
            height=win_h,
            padding=0,
            bgcolor="#0B120B",
            opacity=0.0,
            animate_opacity=ft.Animation(180, ft.AnimationCurve.EASE_OUT),
        )
        self._map_fs_overlay = overlay
        self._map_fs_size = (win_w, win_h)

        try:
            # Ensure we sit on top of any other overlays
            page.overlay.append(overlay)
            page.update()
        except Exception:
            # restore if overlay fails
            self._map_fullscreen = False
            host.content = map_view
            try:
                host.update()
            except Exception:
                pass
            self._map_fs_overlay = None
            self._map_fs_body = None
            return

        def _animate_in() -> None:
            try:
                # Re-measure in case window size is available only after paint
                w2, h2 = self._page_window_size(page)
                if (w2, h2) != (win_w, win_h):
                    overlay.width = w2
                    overlay.height = h2
                    mw = max(400, w2)
                    mh = max(300, h2 - bar_h)
                    map_body.width = mw
                    map_body.height = mh
                    try:
                        map_view.resize_map(mw, mh, refit=True)
                    except TypeError:
                        try:
                            map_view.resize_map(mw, mh)
                            if hasattr(map_view, "fit_to_view"):
                                map_view.fit_to_view()
                        except Exception:
                            pass
                    except Exception:
                        pass
                overlay.opacity = 1.0
                map_body.scale = 1.0
                map_body.opacity = 1.0
                overlay.update()
                map_body.update()
            except Exception:
                pass

        try:
            page.run_task(self._async_call, _animate_in)
        except Exception:
            _animate_in()

        btn = getattr(self, "_map_fullscreen_btn", None)
        if btn is not None:
            btn.set_text("⛶ 退出")
            safe_update(btn)

    def _exit_map_fullscreen(self) -> None:
        page = getattr(getattr(self, "app", None), "page", None)
        map_view = getattr(self, "_map_view", None)
        host = getattr(self, "_map_inline_parent", None) or getattr(self, "_map_host", None)
        overlay = getattr(self, "_map_fs_overlay", None)
        body = getattr(self, "_map_fs_body", None)

        def _restore() -> None:
            self._map_fullscreen = False
            # Remove overlay
            if page is not None and overlay is not None:
                try:
                    if overlay in page.overlay:
                        page.overlay.remove(overlay)
                    page.update()
                except Exception:
                    pass
            self._map_fs_overlay = None
            self._map_fs_body = None

            # Reattach map to inline host
            if host is not None and map_view is not None:
                host.content = map_view
                try:
                    host.update()
                except Exception:
                    pass
            if map_view is not None:
                pre = getattr(self, "_map_pre_fs_size", None)
                if pre:
                    map_view.resize_map(pre[0], pre[1])
                elif hasattr(map_view, "_schedule_rebuild"):
                    map_view._schedule_rebuild()

            # Tab-only fallback cleanup
            side = getattr(self, "_region_side_panel", None)
            if side is not None and getattr(side, "visible", True) is False:
                side.visible = True
                try:
                    side.update()
                except Exception:
                    pass

            btn = getattr(self, "_map_fullscreen_btn", None)
            if btn is not None:
                btn.set_text("⛶ 全屏")
                safe_update(btn)

        # Animate out then restore
        if overlay is not None and body is not None:
            try:
                overlay.opacity = 0.0
                body.scale = 0.96
                body.opacity = 0.0
                overlay.update()
                body.update()
            except Exception:
                pass

            def _after() -> None:
                import time
                time.sleep(0.18)
                if page is not None:
                    from app.ui.utils import run_on_ui
                    run_on_ui(page, _restore)
                else:
                    _restore()

            import threading
            threading.Thread(target=_after, daemon=True).start()
        else:
            _restore()

    async def _async_call(self, fn) -> None:
        """Run a sync callback after yielding to the UI loop (for enter animation)."""
        import asyncio
        await asyncio.sleep(0.02)
        try:
            fn()
        except Exception:
            pass

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
        return "🗺️ 俯视图例", [
            ("#228B22", "草地", "植被"),
            ("#64A4DF", "水体", "海/河"),
            ("#EED6AF", "沙地", "沙漠"),
            ("#808080", "岩石", "石/深板岩"),
            ("#4CAF50", "占位", "未加载"),
            ("#FFD54F", "选中", "边框"),
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
            self._region_stats_text.value = f"已生成区域: {total} 个"
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
            f"区域 ({region_x}, {region_z})\n"
            f"r.{region_x}.{region_z}.mca\n"
            f"区块 X{chunk_x0}~{chunk_x1} Z{chunk_z0}~{chunk_z1}\n"
            f"方块 X{block_x0}~{block_x1} Z{block_z0}~{block_z1}"
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
        self._region_stats_text.value = f"已生成区域: {total} 个"
        self._region_stats_text.color = THEME.text_primary
        safe_update(self._region_stats_text)
