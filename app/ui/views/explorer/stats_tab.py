"""Stats tab mixin for ExplorerView."""
import threading
from typing import Any, List, Tuple

import flet as ft
import flet.canvas as cv

from app.ui.theme import THEME
from app.ui.components.cards import card
from app.ui.views.explorer.utils import safe_update, format_size
from app.ui.views.explorer.mixin_context import ExplorerMixinHost


class StatsTabMixin(ExplorerMixinHost):
    """Build and handle the Explorer statistics tab."""

    def _build_stats_tab(self) -> None:
        """构建统计页签 UI"""
        self._stats_status = ft.Text(
            "设置当前存档后可通过顶栏统计快捷操作分析世界数据。",
            size=12,
            color=THEME.text_muted
        )
        self._stats_summary = ft.Text(
            "通过顶栏统计快捷操作分析世界数据。",
            size=12,
            color=THEME.text_muted
        )
        self._block_stats_col = ft.Column(spacing=4)
        self._entity_stats_col = ft.Column(spacing=4)
        self._size_stats_col = ft.Column(spacing=4)
        self._block_pie_canvas = cv.Canvas(
            width=260,
            height=220,
            shapes=self._build_block_pie_shapes([])
        )
        self._block_pie_legend = ft.Column(spacing=6)

        left_stats = ft.Container(
            content=ft.Column([
                card(self._stats_status, padding=12),
                card(
                    ft.Column([
                        ft.Text(
                            "汇总",
                            size=14,
                            weight=ft.FontWeight.BOLD,
                            color=THEME.text_primary
                        ),
                        self._stats_summary
                    ], spacing=8),
                    padding=12
                ),
                card(
                    ft.Column([
                        ft.Text(
                            "方块分布 Top 10",
                            size=14,
                            weight=ft.FontWeight.BOLD,
                            color=THEME.text_primary
                        ),
                        self._block_stats_col
                    ], spacing=8),
                    padding=12
                ),
                card(
                    ft.Column([
                        ft.Text(
                            "实体数量 Top 10",
                            size=14,
                            weight=ft.FontWeight.BOLD,
                            color=THEME.text_primary
                        ),
                        self._entity_stats_col
                    ], spacing=8),
                    padding=12
                ),
                card(
                    ft.Column([
                        ft.Text(
                            "区域文件大小分布",
                            size=14,
                            weight=ft.FontWeight.BOLD,
                            color=THEME.text_primary
                        ),
                        self._size_stats_col
                    ], spacing=8),
                    padding=12
                ),
            ], spacing=12),
            col={"xs": 12, "sm": 12, "md": 7, "lg": 8}
        )

        right_stats = ft.Container(
            content=card(
                ft.Column([
                    ft.Text(
                        "方块占比分析（已排除空气）",
                        size=14,
                        weight=ft.FontWeight.BOLD,
                        color=THEME.text_primary
                    ),
                    ft.Container(
                        content=self._block_pie_canvas,
                        alignment=ft.alignment.Alignment(0, 0)
                    ),
                    self._block_pie_legend,
                ], spacing=10),
                padding=12
            ),
            col={"xs": 12, "sm": 12, "md": 5, "lg": 4}
        )

        stats_layout = ft.ResponsiveRow([left_stats, right_stats], spacing=12)
        self._tab_stats.content = ft.Column(
            [stats_layout],
            spacing=12,
            scroll=ft.ScrollMode.AUTO
        )

    def _build_block_pie_shapes(
            self, items: List[Tuple[str, int]]) -> List[cv.Shape]:
        """构建方块分布饼图的形状列表"""
        colors = [
            "#66BB6A", "#42A5F5", "#FFA726",
            "#AB47BC", "#EF5350", "#26A69A", "#D4E157"
        ]
        shapes: List[cv.Shape] = [
            cv.Rect(0, 0, 260, 220, paint=ft.Paint(color=THEME.bg_secondary))
        ]
        total = sum(value for _, value in items)
        if total <= 0:
            shapes.append(
                cv.Text(
                    x=78,
                    y=98,
                    value="暂无方块数据",
                    style=ft.TextStyle(size=13, color=THEME.text_muted)
                )
            )
            return shapes

        start = -90.0
        cx, cy, radius = 130, 104, 76
        shapes.append(
            cv.Circle(
                cx,
                cy,
                radius + 2,
                paint=ft.Paint(
                    color=THEME.border_light)))

        for idx, (_, value) in enumerate(items):
            sweep = value / total * 360
            shapes.append(
                cv.Arc(
                    cx - radius,
                    cy - radius,
                    radius * 2,
                    radius * 2,
                    start,
                    sweep,
                    paint=ft.Paint(
                        color=colors[idx % len(colors)],
                        stroke_width=radius,
                        style=ft.PaintingStyle.STROKE
                    ),
                )
            )
            start += sweep

        shapes.append(
            cv.Circle(
                cx, cy, 38, paint=ft.Paint(
                    color=THEME.bg_card)))
        shapes.append(
            cv.Text(
                x=102,
                y=96,
                value="TOP",
                style=ft.TextStyle(size=13, color=THEME.text_primary)
            )
        )
        shapes.append(
            cv.Text(
                x=98,
                y=113,
                value="方块",
                style=ft.TextStyle(size=12, color=THEME.text_muted)
            )
        )
        return shapes

    def _update_block_pie_chart(self, items: List[Tuple[str, int]]) -> None:
        """更新方块分布饼图和图例"""
        pie_items = items[:7]
        total = sum(value for _, value in pie_items)
        colors = [
            "#66BB6A", "#42A5F5", "#FFA726",
            "#AB47BC", "#EF5350", "#26A69A", "#D4E157"
        ]
        self._block_pie_canvas.shapes = self._build_block_pie_shapes(pie_items)
        self._block_pie_legend.controls.clear()
        if total <= 0:
            self._block_pie_legend.controls.append(
                ft.Text("暂无数据", size=12, color=THEME.text_muted)
            )
        else:
            for idx, (name, value) in enumerate(pie_items):
                percent = value / total * 100
                self._block_pie_legend.controls.append(
                    ft.Row([
                        ft.Container(
                            width=12,
                            height=12,
                            bgcolor=colors[idx % len(colors)],
                            border_radius=2
                        ),
                        ft.Text(
                            str(name),
                            size=11,
                            color=THEME.text_secondary,
                            width=150
                        ),
                        ft.Text(
                            f"{percent:.1f}%",
                            size=11,
                            color=THEME.text_muted
                        ),
                    ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)
                )

    def _fill_rank(self, col: ft.Column, items: List[Tuple[str, int]]) -> None:
        """填充排名列表（通用：方块、实体、文件大小等）"""
        col.controls.clear()
        if not items:
            col.controls.append(
                ft.Text("暂无数据", size=12, color=THEME.text_muted)
            )
            return
        max_value = max(value for _, value in items) or 1
        for name, value in items:
            col.controls.append(
                ft.Row([
                    ft.Text(
                        str(name),
                        size=11,
                        color=THEME.text_secondary,
                        width=240
                    ),
                    ft.ProgressBar(
                        value=value / max_value,
                        width=180,
                        color=THEME.mc_grass,
                        bgcolor=THEME.bg_secondary
                    ),
                    ft.Text(str(value), size=11, color=THEME.text_muted),
                ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)
            )

    def _analyze_world_stats(self, e: Any) -> None:
        """后台分析世界统计数据"""
        try:
            session = self.world_session
            if session is None:
                self.app.warn_dialog("提示", "请先通过侧边栏设置当前存档。")
                return

            from app.services.world_stats_service import get_world_stats_service
            service = get_world_stats_service(log=self.app.log)
            self._stats_status.value = "正在分析，较大存档可能需要较长时间..."
            safe_update(self._stats_status)

            def _run():
                try:
                    stats = service.analyze_world(
                        session.world_path)

                    async def _update_ui():
                        try:
                            chunk_slots = (
                                stats.loaded_chunks + stats.empty_chunks
                            )
                            loaded_ratio = (
                                stats.loaded_chunks / chunk_slots * 100
                                if chunk_slots
                                else 0
                            )
                            total_size = sum(stats.region_sizes.values())
                            self._stats_summary.value = (
                                f"区域: {stats.total_regions}\n"
                                f"已加载区块: {stats.loaded_chunks}，"
                                f"空/未加载槽位: {stats.empty_chunks}，"
                                f"加载比例: {loaded_ratio:.1f}%\n"
                                f"区域文件总大小: {format_size(total_size)}\n"
                                f"方块调色板条目: {stats.total_blocks}，"
                                f"实体/方块实体: {stats.total_entities}"
                            )
                            self._fill_rank(
                                self._block_stats_col,
                                stats.block_stats.top_blocks[:10] if stats.block_stats else []
                            )
                            self._update_block_pie_chart(
                                stats.block_stats.top_blocks[:7] if stats.block_stats else []
                            )
                            self._fill_rank(
                                self._entity_stats_col,
                                stats.entity_stats.top_entities[:10] if stats.entity_stats else []
                            )
                            self._fill_rank(
                                self._size_stats_col, list(
                                    service.get_region_size_distribution(stats).items()))
                            self._stats_status.value = "统计完成。"
                            safe_update(self._tab_stats)
                        except Exception as ex:
                            self.app.handle_exception(ex, title="统计存档失败")

                    self.app.page.run_task(_update_ui)
                except Exception as ex:
                    async def _handle_error(error: Exception):
                        self.app.handle_exception(error, title="统计存档失败")
                    self.app.page.run_task(_handle_error, ex)

            threading.Thread(target=_run, daemon=True).start()
        except Exception as ex:
            self.app.handle_exception(ex, title="统计存档失败")
