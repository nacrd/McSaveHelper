"""Stats tab mixin for ExplorerView."""
import threading
from pathlib import Path
from typing import Any, List, Optional, Tuple

import flet as ft
import flet.canvas as cv

from app.ui.theme import THEME
from app.ui.components.cards import card
from app.ui.utils import run_on_ui
from app.ui.views.explorer.utils import safe_update, format_size
from app.ui.views.explorer.mixin_context import ExplorerMixinHost
from app.services.world_stats_service import (
    PLAYER_SORT_DAMAGE,
    PLAYER_SORT_DEATHS,
    PLAYER_SORT_DISTANCE,
    PLAYER_SORT_JUMPS,
    PLAYER_SORT_MINED,
    PLAYER_SORT_MOB_KILLS,
    PLAYER_SORT_NAME,
    PLAYER_SORT_OPTIONS,
    PLAYER_SORT_PLACED,
    PLAYER_SORT_PLAY_TIME,
    PLAYER_SORT_PLAYER_KILLS,
    PLAYER_SORT_WORLD_TIME,
    DimensionSizeStats,
    PlayerPlaytimeStats,
    WorldStatistics,
    WorldStatsService,
)


_BLOCK_PIE_COLORS = (
    "#66BB6A",
    "#42A5F5",
    "#FFA726",
    "#AB47BC",
    "#EF5350",
    "#26A69A",
    "#D4E157",
)


class StatsTabMixin(ExplorerMixinHost):
    """Build and handle the Explorer statistics tab."""

    def _build_stats_tab(self) -> None:
        """构建统计页签 UI"""
        self._init_stats_state()
        left_stats = self._build_stats_left_column()
        right_stats = self._build_stats_right_column()
        stats_layout = ft.ResponsiveRow([left_stats, right_stats], spacing=12)
        self._tab_stats.content = ft.Column(
            [stats_layout],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        )

    def _init_stats_state(self) -> None:
        """Create shared stats controls and analysis state."""
        self._stats_generation = 0
        self._stats_busy = False
        self._player_stats_cache: List[PlayerPlaytimeStats] = []
        self._stats_service_cache: Optional[WorldStatsService] = None
        self._player_sort_key = PLAYER_SORT_PLAY_TIME
        self._stats_status = ft.Text(
            self._t(
                "stats.hint_ready",
                "设置当前存档后可通过顶栏「开始统计」分析世界数据。",
            ),
            size=12,
            color=THEME.text_muted,
        )
        self._stats_progress_bar = ft.ProgressBar(
            value=0.0,
            color=THEME.mc_diamond,
            bgcolor=THEME.bg_secondary,
            height=8,
            visible=False,
        )
        self._stats_progress_label = ft.Text(
            "",
            size=11,
            color=THEME.text_muted,
            visible=False,
        )
        self._stats_summary = ft.Text(
            self._t(
                "stats.summary_placeholder",
                "通过顶栏统计快捷操作分析世界数据。",
            ),
            size=12,
            color=THEME.text_muted,
        )
        self._block_stats_col = ft.Column(spacing=4)
        self._entity_stats_col = ft.Column(spacing=4)
        self._size_stats_col = ft.Column(spacing=4)
        self._dimension_stats_col = ft.Column(spacing=4)
        self._player_stats_col = ft.Column(spacing=4)
        self._block_pie_canvas = cv.Canvas(
            width=260,
            height=220,
            shapes=self._build_block_pie_shapes([]),
        )
        self._block_pie_legend = ft.Column(spacing=6)

    def _stats_section_card(
        self,
        title: str,
        body_controls: list[ft.Control],
    ) -> ft.Control:
        return card(
            ft.Column(
                [
                    ft.Text(
                        title,
                        size=14,
                        weight=ft.FontWeight.BOLD,
                        color=THEME.text_primary,
                    ),
                    *body_controls,
                ],
                spacing=8,
            ),
            padding=12,
        )

    def _build_stats_left_column(self) -> ft.Container:
        """Progress/status + summary lists."""
        return ft.Container(
            content=ft.Column(
                [
                    self._build_stats_progress_card(),
                    self._stats_section_card(
                        self._t("stats.section_summary", "汇总"),
                        [self._stats_summary],
                    ),
                    self._stats_section_card(
                        self._t("stats.section_dimensions", "维度大小"),
                        [self._dimension_stats_col],
                    ),
                    self._build_player_stats_card(),
                    self._stats_section_card(
                        self._t("stats.section_blocks", "方块分布 Top 10"),
                        [self._block_stats_col],
                    ),
                    self._stats_section_card(
                        self._t("stats.section_entities", "实体数量 Top 10"),
                        [self._entity_stats_col],
                    ),
                    self._stats_section_card(
                        self._t(
                            "stats.section_region_sizes",
                            "区域文件大小分布",
                        ),
                        [self._size_stats_col],
                    ),
                ],
                spacing=12,
            ),
            col={"xs": 12, "sm": 12, "md": 7, "lg": 8},
        )

    def _build_stats_progress_card(self) -> ft.Control:
        return card(
            ft.Column(
                [
                    self._stats_status,
                    self._stats_progress_label,
                    self._stats_progress_bar,
                ],
                spacing=8,
            ),
            padding=12,
        )

    def _build_player_stats_card(self) -> ft.Control:
        return card(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text(
                                self._t(
                                    "stats.section_playtime",
                                    "玩家统计",
                                ),
                                size=14,
                                weight=ft.FontWeight.BOLD,
                                color=THEME.text_primary,
                                expand=True,
                            ),
                            ft.Text(
                                self._t("stats.sort_by", "排序"),
                                size=11,
                                color=THEME.text_muted,
                            ),
                            self._build_player_sort_dropdown(),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self._player_stats_col,
                ],
                spacing=8,
            ),
            padding=12,
        )

    def _build_stats_right_column(self) -> ft.Container:
        """Block pie chart column."""
        return ft.Container(
            content=card(
                ft.Column(
                    [
                        ft.Text(
                            self._t(
                                "stats.section_block_pie",
                                "方块占比分析（已排除空气）",
                            ),
                            size=14,
                            weight=ft.FontWeight.BOLD,
                            color=THEME.text_primary,
                        ),
                        ft.Container(
                            content=self._block_pie_canvas,
                            alignment=ft.Alignment(0, 0),
                        ),
                        self._block_pie_legend,
                    ],
                    spacing=10,
                ),
                padding=12,
            ),
            col={"xs": 12, "sm": 12, "md": 5, "lg": 4},
        )

    def _build_block_pie_shapes(
            self, items: List[Tuple[str, int]]) -> List[cv.Shape]:
        """构建方块分布饼图的形状列表"""
        colors = _BLOCK_PIE_COLORS
        shapes: List[cv.Shape] = [
            cv.Rect(0, 0, 260, 220, paint=ft.Paint(color=THEME.bg_secondary))
        ]
        total = sum(value for _, value in items)
        if total <= 0:
            shapes.append(self._empty_pie_text())
            return shapes

        shapes.extend(self._pie_slices(items, total, colors))
        shapes.extend(self._pie_center_labels())
        return shapes

    def _empty_pie_text(self) -> cv.Text:
        return cv.Text(
            x=78,
            y=98,
            value=self._t("stats.pie_empty", "暂无方块数据"),
            style=ft.TextStyle(size=13, color=THEME.text_muted),
        )

    def _pie_slices(
        self,
        items: List[Tuple[str, int]],
        total: int,
        colors: List[str],
    ) -> List[cv.Shape]:
        shapes: List[cv.Shape] = []
        start = -90.0
        cx, cy, radius = 130, 104, 76
        shapes.append(
            cv.Circle(
                cx,
                cy,
                radius + 2,
                paint=ft.Paint(color=THEME.border_light),
            )
        )
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
                        style=ft.PaintingStyle.STROKE,
                    ),
                )
            )
            start += sweep
        return shapes

    def _pie_center_labels(self) -> List[cv.Shape]:
        return [
            cv.Circle(130, 104, 38, paint=ft.Paint(color=THEME.bg_card)),
            cv.Text(
                x=102,
                y=96,
                value="TOP",
                style=ft.TextStyle(size=13, color=THEME.text_primary),
            ),
            cv.Text(
                x=98,
                y=113,
                value=self._t("stats.pie_center", "方块"),
                style=ft.TextStyle(size=12, color=THEME.text_muted),
            ),
        ]

    def _update_block_pie_chart(self, items: List[Tuple[str, int]]) -> None:
        """更新方块分布饼图和图例"""
        pie_items = items[:7]
        total = sum(value for _, value in pie_items)
        colors = _BLOCK_PIE_COLORS
        self._block_pie_canvas.shapes = self._build_block_pie_shapes(pie_items)
        self._block_pie_legend.controls.clear()
        if total <= 0:
            self._block_pie_legend.controls.append(
                ft.Text(
                    self._t("stats.no_data", "暂无数据"),
                    size=12,
                    color=THEME.text_muted,
                )
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
                ft.Text(
                    self._t("stats.no_data", "暂无数据"),
                    size=12,
                    color=THEME.text_muted,
                )
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

    def _fill_dimension_stats(
        self,
        dimensions: List[DimensionSizeStats],
    ) -> None:
        col = self._dimension_stats_col
        col.controls.clear()
        if not dimensions:
            col.controls.append(
                ft.Text(
                    self._t("stats.no_data", "暂无数据"),
                    size=12,
                    color=THEME.text_muted,
                )
            )
            return
        max_bytes = max(item.total_bytes for item in dimensions) or 1
        for item in dimensions:
            label = item.display_name or item.dimension_id
            col.controls.append(
                ft.Column([
                    ft.Row([
                        ft.Text(
                            label,
                            size=11,
                            color=THEME.text_secondary,
                            expand=True,
                        ),
                        ft.Text(
                            format_size(item.total_bytes),
                            size=11,
                            color=THEME.text_muted,
                        ),
                    ], spacing=8),
                    ft.ProgressBar(
                        value=item.total_bytes / max_bytes,
                        width=None,
                        color=THEME.mc_grass,
                        bgcolor=THEME.bg_secondary,
                    ),
                    ft.Text(
                        self._t(
                            "stats.dimension_regions",
                            "{count} 个区域文件",
                            count=item.region_count,
                        ),
                        size=10,
                        color=THEME.text_muted,
                    ),
                ], spacing=2)
            )

    def _build_player_sort_dropdown(self) -> ft.Dropdown:
        options = [
            ft.dropdown.Option(
                key,
                self._player_sort_label(key),
            )
            for key in PLAYER_SORT_OPTIONS
        ]
        self._player_sort_dropdown = ft.Dropdown(
            options=options,
            value=self._player_sort_key,
            width=160,
            border_color=THEME.border_standard,
            text_size=12,
            on_select=self._on_player_sort_changed,
        )
        return self._player_sort_dropdown

    def _player_sort_label(self, key: str) -> str:
        labels = {
            PLAYER_SORT_PLAY_TIME: self._t(
                "stats.sort_play_time", "游玩时间",
            ),
            PLAYER_SORT_WORLD_TIME: self._t(
                "stats.sort_world_time", "世界时间",
            ),
            PLAYER_SORT_DEATHS: self._t("stats.sort_deaths", "死亡"),
            PLAYER_SORT_MOB_KILLS: self._t(
                "stats.sort_mob_kills", "生物击杀",
            ),
            PLAYER_SORT_PLAYER_KILLS: self._t(
                "stats.sort_player_kills", "玩家击杀",
            ),
            PLAYER_SORT_MINED: self._t("stats.sort_mined", "挖掘"),
            PLAYER_SORT_PLACED: self._t("stats.sort_placed", "使用/放置"),
            PLAYER_SORT_JUMPS: self._t("stats.sort_jumps", "跳跃"),
            PLAYER_SORT_DAMAGE: self._t("stats.sort_damage", "造成伤害"),
            PLAYER_SORT_DISTANCE: self._t("stats.sort_distance", "移动距离"),
            PLAYER_SORT_NAME: self._t("stats.sort_name", "名称"),
        }
        return labels.get(key, key)

    def _on_player_sort_changed(self, event: Any) -> None:
        value = getattr(event.control, "value", None)
        if not value or value not in PLAYER_SORT_OPTIONS:
            return
        self._player_sort_key = str(value)
        if not self._player_stats_cache:
            return
        service = self._stats_service_cache or WorldStatsService()
        sorted_players = WorldStatsService.sort_player_stats(
            self._player_stats_cache,
            self._player_sort_key,
        )
        self._player_stats_cache = sorted_players
        self._fill_player_stats(sorted_players, service)
        safe_update(self._player_stats_col)

    def _fill_player_stats(
        self,
        players: List[PlayerPlaytimeStats],
        service: WorldStatsService,
    ) -> None:
        col = self._player_stats_col
        col.controls.clear()
        if not players:
            col.controls.append(
                ft.Text(
                    self._t("stats.no_player_stats", "未找到玩家 stats 文件"),
                    size=12,
                    color=THEME.text_muted,
                )
            )
            return
        sort_key = getattr(self, "_player_sort_key", PLAYER_SORT_PLAY_TIME)
        metrics = [
            WorldStatsService.player_metric_value(item, sort_key)
            for item in players
        ]
        max_metric = max(metrics) if metrics else 1
        if max_metric <= 0:
            max_metric = 1
        for item in players[:20]:
            display = self._player_display_name(item)
            metric = WorldStatsService.player_metric_value(item, sort_key)
            primary = self._format_player_metric(item, sort_key, service)
            detail = self._t(
                "stats.player_detail",
                "游玩 {duration} · 死亡 {deaths} · 击杀 {kills}"
                " · 挖掘 {mined} · 放置 {placed}",
                duration=service.format_ticks_as_duration(
                    item.play_time_ticks,
                ),
                deaths=item.deaths,
                kills=item.mob_kills,
                mined=item.mined,
                placed=item.placed,
            )
            col.controls.append(
                ft.Column([
                    ft.Row([
                        ft.Text(
                            display,
                            size=11,
                            color=THEME.text_secondary,
                            expand=True,
                        ),
                        ft.Text(
                            primary,
                            size=11,
                            color=THEME.text_muted,
                        ),
                    ], spacing=8),
                    ft.ProgressBar(
                        value=metric / max_metric,
                        width=None,
                        color=THEME.accent,
                        bgcolor=THEME.bg_secondary,
                    ),
                    ft.Text(detail, size=10, color=THEME.text_muted),
                ], spacing=2)
            )

    def _format_player_metric(
        self,
        player: PlayerPlaytimeStats,
        sort_key: str,
        service: WorldStatsService,
    ) -> str:
        if sort_key == PLAYER_SORT_PLAY_TIME:
            return service.format_ticks_as_duration(player.play_time_ticks)
        if sort_key == PLAYER_SORT_WORLD_TIME:
            return service.format_ticks_as_duration(
                player.total_world_time_ticks,
            )
        if sort_key == PLAYER_SORT_DISTANCE:
            meters = player.distance_cm / 100.0
            return self._t(
                "stats.metric_distance",
                "{meters:.1f} m",
                meters=meters,
            )
        if sort_key == PLAYER_SORT_NAME:
            return self._player_display_name(player)
        value = WorldStatsService.player_metric_value(player, sort_key)
        return str(value)

    def _player_display_name(self, player: PlayerPlaytimeStats) -> str:
        """Prefer the resolved player name, else a hyphenated UUID."""
        if player.name:
            return player.name
        from core.omni.player_manager import PlayerManager

        return PlayerManager.format_uuid_with_hyphens(player.uuid)

    @staticmethod
    def _format_uuid_short(uuid: str) -> str:
        from core.omni.player_manager import PlayerManager

        return PlayerManager.format_uuid_with_hyphens(uuid)

    def _analyze_world_stats(self, e: Any) -> None:
        """后台分析世界统计数据"""
        try:
            session = self.world_session
            if session is None:
                self.app.warn_dialog(
                    self._t("common.tip", "提示"),
                    self._t(
                        "stats.need_save",
                        "请先通过侧边栏设置当前存档。",
                    ),
                )
                return
            if getattr(self, "_stats_busy", False):
                return
            if not hasattr(self, "_stats_status"):
                self._build_stats_tab()
                self._tabs_built[3] = True
            self._set_stats_progress_visible(True)
            self._stats_status.value = self._t(
                "stats.analyzing",
                "正在分析，较大存档可能需要较长时间...",
            )
            self._apply_stats_progress(
                0.0,
                self._t("stats.stage_start", "准备分析..."),
            )
            safe_update(self._tab_stats)
            self._switch_tab(3)
            self._start_stats_analysis(session.world_path)
        except Exception as ex:
            self.app.handle_exception(
                ex,
                title=self._t("stats.error_title", "统计存档失败"),
            )

    def _start_stats_analysis(self, world_path: Path) -> None:
        from app.services.world_stats_service import get_world_stats_service

        service = get_world_stats_service(log=self.app.log)
        self._stats_generation = getattr(self, "_stats_generation", 0) + 1
        generation = self._stats_generation
        self._stats_busy = True
        task_name = self._t("stats.progress_task", "统计存档")
        name_map = self._stats_name_map()

        def run() -> None:
            self._run_stats_analysis(
                world_path=world_path,
                service=service,
                generation=generation,
                task_name=task_name,
                name_map=name_map,
            )

        threading.Thread(target=run, daemon=True).start()

    def _stats_name_map(self) -> dict[str, str | None]:
        """Prefer the already-loaded WorldSession name map."""
        name_map: dict[str, str | None] = {}
        session = self.world_session
        if session is None:
            return name_map
        try:
            return dict(session.get_player_names())
        except Exception:
            # Name resolution is optional for stats aggregation.
            return {}

    def _run_stats_analysis(
        self,
        *,
        world_path: Path,
        service: Any,
        generation: int,
        task_name: str,
        name_map: dict[str, str | None],
    ) -> None:
        session = self.world_session
        try:
            run_on_ui(
                self.app.page,
                self.app.show_progress,
                self._t("stats.analyzing", "正在分析存档..."),
            )

            def progress(value: float, stage: str) -> None:
                if generation != getattr(self, "_stats_generation", 0):
                    return
                message = self._format_stats_stage(stage)
                run_on_ui(
                    self.app.page,
                    self.app.update_progress_with_task,
                    message or task_name,
                    value,
                )
                run_on_ui(
                    self.app.page,
                    self._apply_stats_progress,
                    value,
                    message,
                )

            stats = service.analyze_world(
                world_path,
                progress_callback=progress,
                name_map=name_map,
            )
            # Late-bind names that may have been resolved while scanning.
            if session is not None:
                try:
                    latest = dict(session.get_player_names())
                    stats.player_stats = service.with_player_names(
                        stats.player_stats,
                        latest,
                    )
                except Exception:
                    # Sort preference may fail; keep unsorted results.
                    pass
            self.app.page.run_task(
                self._update_stats_ui,
                stats,
                service,
                generation,
            )
        except Exception as ex:
            self.app.page.run_task(
                self._handle_stats_error,
                ex,
                generation,
            )
        finally:
            run_on_ui(self.app.page, self.app.hide_progress)
            run_on_ui(self.app.page, self._finish_stats_busy, generation)

    def _finish_stats_busy(self, generation: int) -> None:
        if generation != getattr(self, "_stats_generation", 0):
            return
        self._stats_busy = False

    def _set_stats_progress_visible(self, visible: bool) -> None:
        if not hasattr(self, "_stats_progress_bar"):
            return
        self._stats_progress_bar.visible = visible
        self._stats_progress_label.visible = visible
        if not visible:
            self._stats_progress_bar.value = 0.0
            self._stats_progress_label.value = ""

    def _apply_stats_progress(self, value: float, message: str) -> None:
        if not hasattr(self, "_stats_progress_bar"):
            return
        clamped = max(0.0, min(1.0, value))
        self._stats_progress_bar.visible = True
        self._stats_progress_label.visible = True
        self._stats_progress_bar.value = clamped
        percent = int(clamped * 100)
        self._stats_progress_label.value = (
            f"{message} {percent}%" if message else f"{percent}%"
        )
        self._stats_status.value = message or self._t(
            "stats.analyzing",
            "正在分析...",
        )
        safe_update(self._stats_progress_bar)
        safe_update(self._stats_progress_label)
        safe_update(self._stats_status)

    def _format_stats_stage(self, stage: str) -> str:
        if stage == "dimensions":
            return self._t("stats.stage_dimensions", "统计维度大小")
        if stage == "players":
            return self._t("stats.stage_players", "读取玩家游玩时间")
        if stage == "scanning":
            return self._t("stats.stage_scanning", "扫描区域文件")
        if stage == "finalizing":
            return self._t("stats.stage_finalizing", "汇总结果")
        if stage == "done":
            return self._t("stats.stage_done", "完成")
        if stage.startswith("regions:"):
            parts = stage.split(":")
            if len(parts) == 3:
                done, total = parts[1], parts[2]
                return self._t(
                    "stats.stage_regions",
                    "分析区域 {done}/{total}",
                    done=done,
                    total=total,
                )
        return stage

    async def _update_stats_ui(
        self,
        stats: WorldStatistics,
        service: WorldStatsService,
        generation: int,
    ) -> None:
        if generation != getattr(self, "_stats_generation", 0):
            return
        try:
            self._set_stats_summary(stats)
            self._set_ranked_stats(stats, service)
            self._fill_dimension_stats(stats.dimension_stats)
            self._stats_service_cache = service
            self._player_stats_cache = WorldStatsService.sort_player_stats(
                list(stats.player_stats),
                getattr(self, "_player_sort_key", PLAYER_SORT_PLAY_TIME),
            )
            self._fill_player_stats(self._player_stats_cache, service)
            self._apply_stats_progress(
                1.0,
                self._t("stats.done", "统计完成。"),
            )
            self._set_stats_progress_visible(False)
            self._stats_status.value = self._t("stats.done", "统计完成。")
            safe_update(self._tab_stats)
        except Exception as ex:
            self.app.handle_exception(
                ex,
                title=self._t("stats.error_title", "统计存档失败"),
            )

    def _set_stats_summary(self, stats: WorldStatistics) -> None:
        chunk_slots = stats.loaded_chunks + stats.empty_chunks
        loaded_ratio = (
            stats.loaded_chunks / chunk_slots * 100 if chunk_slots else 0
        )
        total_size = sum(stats.region_sizes.values())
        dim_total = sum(item.total_bytes for item in stats.dimension_stats)
        self._stats_summary.value = self._t(
            "stats.summary_body",
            "区域: {regions}\n"
            "已加载区块: {loaded}，空/未加载槽位: {empty}，加载比例: {ratio:.1f}%\n"
            "区域文件总大小: {size}\n"
            "维度: {dim_count}（合计 {dim_size}）\n"
            "玩家统计文件: {players}\n"
            "方块条目: {blocks}，实体/方块实体: {entities}",
            regions=stats.total_regions,
            loaded=stats.loaded_chunks,
            empty=stats.empty_chunks,
            ratio=loaded_ratio,
            size=format_size(total_size),
            dim_count=len(stats.dimension_stats),
            dim_size=format_size(dim_total),
            players=len(stats.player_stats),
            blocks=stats.total_blocks,
            entities=stats.total_entities,
        )

    def _set_ranked_stats(
        self, stats: WorldStatistics, service: WorldStatsService
    ) -> None:
        block_items = stats.block_stats.top_blocks if stats.block_stats else []
        entity_items = (
            stats.entity_stats.top_entities if stats.entity_stats else []
        )
        self._fill_rank(self._block_stats_col, block_items[:10])
        self._update_block_pie_chart(block_items[:7])
        self._fill_rank(self._entity_stats_col, entity_items[:10])
        self._fill_rank(
            self._size_stats_col,
            list(service.get_region_size_distribution(stats).items()),
        )

    async def _handle_stats_error(
        self,
        error: Exception,
        generation: Optional[int] = None,
    ) -> None:
        if (
            generation is not None
            and generation != getattr(self, "_stats_generation", 0)
        ):
            return
        self._set_stats_progress_visible(False)
        if hasattr(self, "_stats_status"):
            self._stats_status.value = self._t(
                "stats.error_status",
                "统计失败。",
            )
            safe_update(self._stats_status)
        self.app.handle_exception(
            error,
            title=self._t("stats.error_title", "统计存档失败"),
        )
