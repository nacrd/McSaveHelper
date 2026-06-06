"""存档统计面板视图。"""
from pathlib import Path
from typing import TYPE_CHECKING, Optional, List, Tuple

import flet as ft

from app.services.world_stats_service import WorldStatistics, get_world_stats_service
from app.ui.components.buttons import btn_ghost, btn_primary
from app.ui.components.cards import card, section_title
from app.ui.theme import THEME
from app.ui.utils import format_size as _format_size

if TYPE_CHECKING:
    from app.application import Application


class WorldStatsView(ft.Column):
    def __init__(self, app: "Application") -> None:
        super().__init__(spacing=18, scroll=ft.ScrollMode.AUTO)
        self.expand = True
        self.app = app
        self._service = get_world_stats_service(log=app.log)
        self._stats: Optional[WorldStatistics] = None
        self._build()

    def _build(self) -> None:
        self.controls.clear()
        self.controls.append(ft.Text("存档统计", size=22, weight=ft.FontWeight.BOLD, color=THEME.text_primary))

        self._path_field = ft.TextField(
            label="存档目录",
            hint_text="选择存档目录",
            border_color=THEME.border_tertiary,
            focused_border_color=THEME.mc_diamond,
            text_size=13,
            color=THEME.text_primary,
            bgcolor=THEME.bg_secondary,
            border_radius=0,
            expand=True,
        )
        picker_row = ft.Row([
            self._path_field,
            btn_ghost("浏览", width=90, on_click=self._pick),
            btn_primary("分析", width=90, on_click=self._analyze),
        ], spacing=10)
        self.controls.append(card(picker_row, padding=16))

        self._progress = ft.ProgressBar(value=0, color=THEME.mc_grass, bgcolor=THEME.bg_secondary, height=6, visible=False)
        self._progress_label = ft.Text("", size=11, color=THEME.text_muted)
        self.controls.append(ft.Column([self._progress, self._progress_label], spacing=4))

        self._overview_card = card(ft.Container(ft.Text("请先选择存档并点击「分析」", size=13, color=THEME.text_muted), padding=20))
        self._blocks_card = card(ft.Container(ft.Text("", size=12, color=THEME.text_muted), padding=20))
        self._entities_card = card(ft.Container(ft.Text("", size=12, color=THEME.text_muted), padding=20))
        self._distribution_card = card(ft.Container(ft.Text("", size=12, color=THEME.text_muted), padding=20))

        self.controls.append(ft.Column([
            section_title("总览"), self._overview_card,
            section_title("方块分布 Top 10"), self._blocks_card,
            section_title("实体分布 Top 10"), self._entities_card,
            section_title("区域文件大小分布"), self._distribution_card,
        ], spacing=0))

    def _pick(self, e: ft.ControlEvent) -> None:
        path = self.app.pick_directory()
        if path:
            self._path_field.value = path
            self._path_field.update()

    def _analyze(self, e: ft.ControlEvent) -> None:
        try:
            world_path = Path(self._path_field.value or "")
            if not (world_path / "level.dat").exists():
                self.app.warn_dialog("提示", "请选择包含 level.dat 的有效存档目录。")
                return
            self._progress.visible = True
            self._progress.value = 0
            self._progress_label.value = "正在分析..."
            self.update()

            def on_progress(current: int, total: int) -> None:
                self._progress.value = current / total if total else 0
                self._progress_label.value = f"正在扫描区域 ({current}/{total})..."
                try:
                    self._progress.update()
                    self._progress_label.update()
                except RuntimeError:
                    pass

            self._stats = self._service.analyze_world(world_path, progress_callback=on_progress)
            self._progress.visible = False
            self._progress_label.value = "分析完成"
            self._render_stats()
            self.update()
        except Exception as ex:
            self._progress.visible = False
            self.app.handle_exception(ex, title="分析存档失败")

    def _render_stats(self) -> None:
        if not self._stats:
            return
        s = self._stats
        self._overview_card.content = ft.Container(content=ft.Column([
            self._kv("区域文件", f"{s.total_regions} 个"),
            self._kv("区块总数", f"{s.total_chunks} 个"),
            self._kv("已加载区块", f"{s.loaded_chunks} 个"),
            self._kv("空区块", f"{s.empty_chunks} 个"),
            self._kv("方块种类", f"{len(s.block_stats.block_types) if s.block_stats else 0} 种"),
            self._kv("实体种类", f"{len(s.entity_stats.entity_types) if s.entity_stats else 0} 种"),
            self._kv("区域总大小", _format_size(sum(s.region_sizes.values()))),
        ], spacing=6), padding=20)

        blocks: List[Tuple[str, int]] = s.block_stats.top_blocks[:10] if s.block_stats else []
        self._blocks_card.content = ft.Container(content=self._rank_table(blocks, s.block_stats.total_count if s.block_stats else 0), padding=20)

        entities: List[Tuple[str, int]] = s.entity_stats.top_entities[:10] if s.entity_stats else []
        self._entities_card.content = ft.Container(content=self._rank_table(entities, s.entity_stats.total_count if s.entity_stats else 0), padding=20)

        dist = self._service.get_region_size_distribution(s)
        rows = []
        for label, count in dist.items():
            bar_width = max(4, int(200 * count / max(s.total_regions, 1)))
            rows.append(ft.Row([
                ft.Text(label, size=12, color=THEME.text_secondary, width=120),
                ft.Container(width=float(bar_width), height=16, bgcolor=THEME.mc_grass, border_radius=2),
                ft.Text(f"{count} 个", size=12, color=THEME.text_primary),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER))
        self._distribution_card.content = ft.Container(content=ft.Column(rows, spacing=6), padding=20)

    def _rank_table(self, items: List[Tuple[str, int]], total: int) -> ft.Column:
        if not items:
            return ft.Column([ft.Text("暂无数据", size=12, color=THEME.text_muted)])
        rows = []
        for rank, (name, count) in enumerate(items, 1):
            pct = count / total * 100 if total else 0
            bar_width = max(4, int(200 * count / max(items[0][1], 1)))
            display = name.replace("minecraft:", "")
            rows.append(ft.Row([
                ft.Text(f"{rank}.", size=12, color=THEME.mc_gold, width=28),
                ft.Text(display, size=12, color=THEME.text_primary, width=200, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Container(width=float(bar_width), height=14, bgcolor=THEME.mc_diamond, border_radius=2),
                ft.Text(f"{count:,}", size=11, color=THEME.text_secondary, width=80),
                ft.Text(f"{pct:.1f}%", size=11, color=THEME.text_muted, width=50),
            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER))
        return ft.Column(rows, spacing=4)

    def _kv(self, key: str, value: str) -> ft.Row:
        return ft.Row([
            ft.Text(key, size=13, color=THEME.text_secondary, width=120),
            ft.Text(value, size=13, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
        ], spacing=8)
