"""Entity/Block Search View - 实体/方块搜索视图（三栏布局重构版）"""
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List

import flet as ft

from app.ui.theme import THEME
from app.ui.icons import IconSet
from app.ui.components.buttons import btn_primary, btn_ghost
from app.ui.components.fields import text_field, checkbox, current_save_field, dropdown
from app.ui.components.cards import placeholder
from app.ui.components.layout import page_header
from app.ui.utils import run_on_ui
from app.services.entity_block_search_service import (
    EntityBlockSearchService,
    SearchResult,
)
from app.services.entity_block_search.constants import get_preset_options
from app.services.entity_block_search.models import SearchCondition

if TYPE_CHECKING:
    from app.application import Application


class EntityBlockSearchView(ft.Column):
    """实体/方块/容器搜索视图 - 三栏布局：左侧条件 + 中央结果 + 右侧统计"""

    DISPLAY_LIMIT = 300
    TYPE_LABELS = {
        "entity": "实体",
        "block": "方块",
        "container": "容器",
    }
    DIMENSION_LABELS = {
        "overworld": "主世界",
        "nether": "下界",
        "end": "末地",
    }

    def __init__(self, app: "Application", compact: bool = False) -> None:
        super().__init__(spacing=0, scroll=ft.ScrollMode.AUTO)
        self.app = app
        self._compact = compact
        self.service = EntityBlockSearchService()
        self.expand = True

        self._searching = False
        self._search_results: List[SearchResult] = []
        self._last_search_meta: Dict[str, Any] = {}

        self._init_controls()
        self._build_ui()

    def _init_controls(self) -> None:
        """初始化所有控件"""
        self._world_path_field = current_save_field(
            hint_text="请通过侧边栏「设置当前存档」设置要搜索的当前存档目录",
        )

        self._search_type_dropdown = dropdown(
            label="搜索范围",
            options=[
                ft.dropdown.Option("entity", "实体"),
                ft.dropdown.Option("block", "方块"),
                ft.dropdown.Option("container", "容器"),
            ],
            value="entity",
            width=250,
            on_change=self._on_search_type_change,
        )

        self._target_field = text_field(
            label="目标 ID",
            hint_text="例如: villager、*shulker*、zombie,cow",
            width=250,
        )

        self._preset_chips = ft.Row(wrap=True, spacing=4)
        self._update_presets()

        # 维度选择
        self._dim_overworld = checkbox("主世界", True)
        self._dim_nether = checkbox("下界", True)
        self._dim_end = checkbox("末地", True)

        # 状态显示
        self._status_title_text = ft.Text(
            "未开始搜索",
            size=13,
            weight=ft.FontWeight.BOLD,
            color=THEME.text_primary,
        )
        self._status_summary_text = ft.Text(
            "", size=12, color=THEME.text_secondary)
        self._status_progress = ft.ProgressBar(width=200, visible=False)

        # 搜索按钮
        self._search_btn = btn_primary(
            "🔍 开始搜索", on_click=self._start_search, height=40)
        self._export_btn = btn_ghost(
            "📊 导出结果", on_click=self._export_results, height=40)

        # 结果列表容器
        self._results_list = ft.Column(spacing=4, scroll=ft.ScrollMode.AUTO)

    def _build_ui(self) -> None:
        """构建三栏布局 UI"""
        self.controls.clear()

        # 顶部标题
        header = page_header(
            "实体/方块搜索",
            ft.Text("按维度搜索实体、方块和容器，并查看命中详情", size=12, color=THEME.text_muted),
            icon=IconSet.SEARCH,
        )

        # 三栏布局
        left_panel = self._build_left_panel()
        center_panel = self._build_center_panel()
        right_panel = self._build_right_panel()

        main_row = ft.Row(
            [left_panel, center_panel, right_panel],
            spacing=8,
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )

        self.controls = [
            header,
            ft.Container(height=4),
            ft.Container(content=main_row, padding=10, expand=True),
        ]

    # ==================== 左侧搜索条件面板 ====================

    def _build_left_panel(self) -> ft.Container:
        """构建左侧搜索条件面板"""
        criteria_section = ft.Column([
            ft.Text("🔍 搜索条件", size=13, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
            self._world_path_field,
            self._search_type_dropdown,
            self._target_field,
            ft.Text("常用预设（点击填入）", size=10, color=THEME.text_muted),
            self._preset_chips,
            ft.Text(
                "支持通配符 * 和逗号分隔多目标",
                size=10,
                color=THEME.text_muted,
            ),
        ], spacing=8)

        dimension_section = ft.Column([
            ft.Divider(height=1, color=THEME.border_light),
            ft.Text("🌍 维度", size=13, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
            self._dim_overworld,
            self._dim_nether,
            self._dim_end,
        ], spacing=6)

        action_section = ft.Column([
            ft.Divider(height=1, color=THEME.border_light),
            ft.Container(content=self._search_btn, expand=True),
            ft.Container(content=self._export_btn, expand=True),
        ], spacing=6)

        left_content = ft.Column(
            [criteria_section, dimension_section, action_section],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        )

        return ft.Container(
            content=left_content,
            width=280,
            bgcolor=THEME.bg_card,
            border=ft.Border.all(1, THEME.border_light),
            border_radius=8,
            padding=12,
        )

    # ==================== 中央搜索结果面板 ====================

    def _build_center_panel(self) -> ft.Container:
        """构建中央搜索结果面板"""
        toolbar = ft.Row([
            ft.Text("搜索结果", size=13, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
            ft.Container(expand=True),
            self._status_progress,
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        results_container = ft.Container(
            content=self._results_list,
            bgcolor=THEME.bg_secondary,
            border_radius=4,
            padding=4,
            expand=True,
        )

        self._results_list.controls.append(
            placeholder(
                icon=IconSet.SEARCH,
                title="尚未搜索",
                subtitle="设置搜索条件后点击「开始搜索」",
                height=200,
            )
        )

        center_content = ft.Column(
            [toolbar, results_container],
            spacing=8,
            expand=True,
        )

        return ft.Container(
            content=center_content,
            expand=True,
            bgcolor=THEME.bg_card,
            border=ft.Border.all(1, THEME.border_light),
            border_radius=8,
            padding=12,
        )

    # ==================== 右侧统计/帮助面板 ====================

    def _build_right_panel(self) -> ft.Container:
        """构建右侧统计和帮助面板"""
        status_section = ft.Column([
            ft.Text("📊 搜索状态", size=13, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
            self._status_title_text,
            self._status_summary_text,
        ], spacing=6)

        help_section = ft.Column([
            ft.Divider(height=1, color=THEME.border_light),
            ft.Text("ℹ️ 使用帮助", size=13, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
            ft.Text(
                "1. 选择搜索范围（实体/方块/容器）\n"
                "2. 输入目标 ID\n"
                "3. 选择要搜索的维度\n"
                "4. 点击开始搜索\n\n"
                "目标 ID 示例：\n"
                "• villager — 匹配村民\n"
                "• *shulker* — 匹配所有潜影盒\n"
                "• zombie,cow — 同时搜索多个目标\n"
                "• * — 搜索所有",
                size=11,
                color=THEME.text_muted,
            ),
        ], spacing=6)

        right_content = ft.Column(
            [status_section, help_section],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        )

        return ft.Container(
            content=right_content,
            width=280,
            bgcolor=THEME.bg_card,
            border=ft.Border.all(1, THEME.border_light),
            border_radius=8,
            padding=12,
        )

    # ==================== 功能方法 ====================

    def on_save_selected(self, path: str) -> None:
        """当存档被选择时调用"""
        self._world_path_field.value = path
        if hasattr(self._world_path_field, 'update'):
            self._world_path_field.update()

    def _on_search_type_change(self, e: Any) -> None:
        """搜索范围改变时更新预设标签"""
        self._update_presets()
        self._preset_chips.update()

    def _update_presets(self) -> None:
        """根据当前搜索范围刷新预设快捷标签"""
        search_type = self._search_type_dropdown.value or "entity"
        presets = get_preset_options(search_type)
        self._preset_chips.controls.clear()
        for preset_id, label in presets:
            chip = ft.Container(
                content=ft.Text(
                    label, size=11, color=THEME.text_primary,
                    no_wrap=True,
                ),
                bgcolor=THEME.bg_secondary,
                border=ft.Border.all(1, THEME.border_subtle),
                border_radius=12,
                padding=ft.Padding(left=8, right=8, top=3, bottom=3),
                on_click=lambda e, pid=preset_id: self._fill_target(pid),
                tooltip=preset_id,
            )
            self._preset_chips.controls.append(chip)

    def _fill_target(self, preset_id: str) -> None:
        """点击预设标签后填入目标 ID"""
        self._target_field.value = preset_id
        self._target_field.update()

    def _start_search(self, e: Any = None) -> None:
        """开始搜索"""
        if self._searching:
            self.app.warn_dialog("搜索中", "当前正在搜索，请等待完成")
            return

        world_path = self._world_path_field.value
        if not world_path:
            self.app.warn_dialog("提示", "请先设置当前存档")
            return

        target = (self._target_field.value or "").strip()
        if not target:
            self.app.warn_dialog("提示", "请输入目标 ID")
            return

        dim_checks = (
            (self._dim_overworld, "overworld"),
            (self._dim_nether, "nether"),
            (self._dim_end, "end"),
        )
        dimensions = [dim for control, dim in dim_checks if control.value]

        condition = SearchCondition(
            search_type=self._search_type_dropdown.value or "entity",
            target=target,
            dimensions=dimensions,
            world_path=Path(world_path),
        )
        errors = condition.validate()
        if errors:
            self.app.warn_dialog("提示", errors[0])
            return

        # 开始搜索
        self._searching = True
        self._search_btn.disabled = True
        self._search_btn.update()

        self._status_title_text.value = "🔄 搜索中..."
        self._status_title_text.color = THEME.mc_gold
        self._status_progress.visible = True
        self._status_title_text.update()
        self._status_progress.update()

        def _search():
            try:
                results = self.service.search(
                    world_path=condition.world_path,
                    search_type=condition.search_type,
                    target=condition.target,
                    dimensions=condition.dimensions,
                )
                result_controls = self._build_result_controls(results)

                def _update_ui():
                    self._search_results = results
                    self._last_search_meta = {
                        "type": condition.search_type,
                        "target": condition.target,
                        "dimensions": condition.dimensions,
                    }
                    self._render_results(result_controls)
                    self._status_title_text.value = "✅ 搜索完成"
                    self._status_title_text.color = THEME.mc_grass
                    self._status_summary_text.value = f"找到 {len(results)} 个结果"
                    self._status_progress.visible = False
                    self._searching = False
                    self._search_btn.disabled = False
                    self._status_title_text.update()
                    self._status_summary_text.update()
                    self._status_progress.update()
                    self._search_btn.update()

                run_on_ui(self.app.page, _update_ui)

            except Exception as ex:
                error_msg = str(ex)
                exception = ex

                def _show_error():
                    self._status_title_text.value = "❌ 搜索失败"
                    self._status_title_text.color = THEME.error
                    self._status_summary_text.value = error_msg
                    self._status_progress.visible = False
                    self._searching = False
                    self._search_btn.disabled = False
                    self._status_title_text.update()
                    self._status_summary_text.update()
                    self._status_progress.update()
                    self._search_btn.update()
                    self.app.handle_exception(exception, title="搜索失败")

                run_on_ui(self.app.page, _show_error)

        threading.Thread(target=_search, daemon=True).start()

    def _build_result_controls(
        self,
        results: List[SearchResult],
    ) -> List[ft.Control]:
        """Create detached result controls without occupying the UI loop."""
        controls: List[ft.Control] = []
        if not results:
            controls.append(
                placeholder(
                    icon=IconSet.SEARCH,
                    title="未找到结果",
                    subtitle="尝试修改搜索条件",
                    height=200,
                )
            )
        else:
            displayed = min(len(results), self.DISPLAY_LIMIT)
            controls.extend(
                self._build_result_row(index, result)
                for index, result in enumerate(results[:displayed])
            )

            if len(results) > displayed:
                controls.append(
                    ft.Text(
                        f"显示前 {displayed} 个结果，共 {len(results)} 个",
                        size=12,
                        color=THEME.warning,
                    )
                )
        return controls

    def _render_results(
        self,
        controls: List[ft.Control] | None = None,
    ) -> None:
        """Attach prepared search controls and refresh once."""
        rendered = (
            controls
            if controls is not None
            else self._build_result_controls(self._search_results)
        )
        self._results_list.controls.clear()
        self._results_list.controls.extend(rendered)
        self._results_list.update()

    def _build_result_row(
            self,
            index: int,
            result: SearchResult) -> ft.Container:
        """构建单个结果行"""
        dim_label = self.DIMENSION_LABELS.get(
            result.dimension, result.dimension)
        pos_text = f"({result.x}, {result.y}, {result.z})"

        return ft.Container(
            content=ft.Row([
                ft.Text(f"#{index + 1}", size=11, color=THEME.mc_gold, width=40),
                ft.Column([
                    ft.Text(
                        result.target_id,
                        size=12,
                        weight=ft.FontWeight.BOLD,
                        color=THEME.text_primary,
                    ),
                    ft.Text(f"{dim_label} {pos_text}", size=11, color=THEME.text_muted),
                ], spacing=2, expand=True),
            ], spacing=8),
            bgcolor=THEME.bg_card if index % 2 == 0 else THEME.bg_secondary,
            padding=8,
            border_radius=4,
        )

    def _export_results(self, e: Any = None) -> None:
        """导出搜索结果"""
        if not self._search_results:
            self.app.warn_dialog("提示", "没有可导出的搜索结果")
            return

        try:
            path = self.app.save_file(
                title="导出搜索结果",
                default_ext=".csv",
                file_types=[("CSV 文件", "*.csv")]
            )
            if path:
                self.service.export_results(self._search_results, Path(path))
                self.app.info_dialog(
                    "导出成功", f"已导出 {len(self._search_results)} 个结果到：\n{path}")
        except Exception as ex:
            self.app.handle_exception(ex, title="导出失败")
