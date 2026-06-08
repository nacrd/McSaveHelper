"""Entity/Block Search View - 实体/方块搜索视图（三栏布局重构版）"""
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List

import flet as ft

from app.ui.theme import THEME
from app.ui.components.buttons import btn_primary, btn_ghost
from app.ui.components.fields import text_field, checkbox, current_save_field
from app.ui.components.cards import card, placeholder
from app.ui.components.layout import page_header, section_header
from app.services.entity_block_search_service import (
    EntityBlockSearchService,
    SearchResult,
)

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
        self._sync_target_source_ui(update=False)

    def _init_controls(self) -> None:
        """初始化所有控件"""
        self._world_path_field = current_save_field(
            hint_text="请通过侧边栏「设置当前存档」设置要搜索的当前存档目录",
        )

        self._search_type_dropdown = ft.Dropdown(
            label="搜索范围",
            options=[
                ft.dropdown.Option("entity", "🐾 实体"),
                ft.dropdown.Option("block", "🧱 方块"),
                ft.dropdown.Option("container", "📦 容器"),
            ],
            value="entity",
            bgcolor=THEME.bg_secondary,
            border_color=THEME.border_subtle,
            color=THEME.text_primary,
            width=250,
        )
        self._search_type_dropdown.on_change = self._on_search_type_change

        self._target_source_dropdown = ft.Dropdown(
            label="目标来源",
            options=[
                ft.dropdown.Option("preset", "使用预设"),
                ft.dropdown.Option("custom", "输入 ID"),
            ],
            value="preset",
            bgcolor=THEME.bg_secondary,
            border_color=THEME.border_subtle,
            color=THEME.text_primary,
            width=250,
        )
        self._target_source_dropdown.on_change = self._on_target_source_change

        self._target_dropdown = ft.Dropdown(
            label="实体类型",
            options=self._get_entity_options(),
            bgcolor=THEME.bg_secondary,
            border_color=THEME.border_subtle,
            color=THEME.text_primary,
            width=250,
        )

        self._custom_target_field = text_field(
            label="自定义目标 ID",
            hint_text="例如: minecraft:villager 或 villager",
            width=250,
        )

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
        self._status_summary_text = ft.Text("", size=12, color=THEME.text_secondary)
        self._status_progress = ft.ProgressBar(width=200, visible=False)

        # 搜索按钮
        self._search_btn = btn_primary("🔍 开始搜索", on_click=self._start_search, height=40)
        self._export_btn = btn_ghost("📊 导出结果", on_click=self._export_results, height=40)

        # 结果列表容器
        self._results_list = ft.Column(spacing=4, scroll=ft.ScrollMode.AUTO)

    def _build_ui(self) -> None:
        """构建三栏布局 UI"""
        self.controls.clear()

        # 顶部标题
        header = page_header(
            "实体/方块搜索",
            ft.Text("按维度搜索实体、方块和容器，并查看命中详情", size=12, color=THEME.text_muted),
            icon="🔍",
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
        # 搜索条件
        criteria_section = ft.Column([
            ft.Text("🔍 搜索条件", size=13, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
            self._world_path_field,
            self._search_type_dropdown,
            self._target_source_dropdown,
            self._target_dropdown,
            self._custom_target_field,
            ft.Text(
                "提示：使用预设时会忽略自定义 ID",
                size=10,
                color=THEME.text_muted,
            ),
        ], spacing=8)

        # 维度选择
        dimension_section = ft.Column([
            ft.Divider(height=1, color=THEME.border_light),
            ft.Text("🌍 维度", size=13, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
            self._dim_overworld,
            self._dim_nether,
            self._dim_end,
        ], spacing=6)

        # 搜索按钮
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
            border=ft.border.all(1, THEME.border_light),
            border_radius=8,
            padding=12,
        )

    # ==================== 中央搜索结果面板 ====================

    def _build_center_panel(self) -> ft.Container:
        """构建中央搜索结果面板"""
        # 顶部工具栏
        toolbar = ft.Row([
            ft.Text("搜索结果", size=13, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
            ft.Container(expand=True),
            self._status_progress,
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        # 结果容器
        results_container = ft.Container(
            content=self._results_list,
            bgcolor=THEME.bg_secondary,
            border_radius=4,
            padding=4,
            expand=True,
        )

        # 初始占位符
        self._results_list.controls.append(
            placeholder(
                icon="🔍",
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
            border=ft.border.all(1, THEME.border_light),
            border_radius=8,
            padding=12,
        )

    # ==================== 右侧统计/帮助面板 ====================

    def _build_right_panel(self) -> ft.Container:
        """构建右侧统计和帮助面板"""
        # 搜索状态
        status_section = ft.Column([
            ft.Text("📊 搜索状态", size=13, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
            self._status_title_text,
            self._status_summary_text,
        ], spacing=6)

        # 帮助信息
        help_section = ft.Column([
            ft.Divider(height=1, color=THEME.border_light),
            ft.Text("ℹ️ 使用帮助", size=13, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
            ft.Text(
                "1. 选择搜索范围（实体/方块/容器）\n"
                "2. 选择目标来源（预设/自定义）\n"
                "3. 选择要搜索的维度\n"
                "4. 点击开始搜索",
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
            border=ft.border.all(1, THEME.border_light),
            border_radius=8,
            padding=12,
        )

    # ==================== 以下是原有的方法（保留功能逻辑）====================

    def on_save_selected(self, path: str) -> None:
        """当存档被选择时调用"""
        self._world_path_field.value = path
        if hasattr(self._world_path_field, 'update'):
            self._world_path_field.update()

    def _get_entity_options(self) -> List[ft.dropdown.Option]:
        """获取实体预设选项"""
        entities = [
            ("minecraft:villager", "村民"),
            ("minecraft:zombie", "僵尸"),
            ("minecraft:skeleton", "骷髅"),
            ("minecraft:creeper", "苦力怕"),
            ("minecraft:spider", "蜘蛛"),
            ("minecraft:enderman", "末影人"),
            ("minecraft:pig", "猪"),
            ("minecraft:cow", "牛"),
            ("minecraft:sheep", "羊"),
            ("minecraft:chicken", "鸡"),
        ]
        return [ft.dropdown.Option(id, f"{name} ({id})") for id, name in entities]

    def _get_block_options(self) -> List[ft.dropdown.Option]:
        """获取方块预设选项"""
        blocks = [
            ("minecraft:diamond_ore", "钻石矿石"),
            ("minecraft:iron_ore", "铁矿石"),
            ("minecraft:gold_ore", "金矿石"),
            ("minecraft:coal_ore", "煤矿石"),
            ("minecraft:emerald_ore", "绿宝石矿石"),
            ("minecraft:ancient_debris", "远古残骸"),
        ]
        return [ft.dropdown.Option(id, f"{name} ({id})") for id, name in blocks]

    def _get_container_options(self) -> List[ft.dropdown.Option]:
        """获取容器预设选项"""
        containers = [
            ("minecraft:chest", "箱子"),
            ("minecraft:barrel", "木桶"),
            ("minecraft:shulker_box", "潜影盒"),
            ("minecraft:hopper", "漏斗"),
            ("minecraft:furnace", "熔炉"),
        ]
        return [ft.dropdown.Option(id, f"{name} ({id})") for id, name in containers]

    def _on_search_type_change(self, e: Any) -> None:
        """搜索类型改变时更新预设选项"""
        search_type = self._search_type_dropdown.value
        if search_type == "entity":
            self._target_dropdown.label = "实体类型"
            self._target_dropdown.options = self._get_entity_options()
        elif search_type == "block":
            self._target_dropdown.label = "方块类型"
            self._target_dropdown.options = self._get_block_options()
        elif search_type == "container":
            self._target_dropdown.label = "容器类型"
            self._target_dropdown.options = self._get_container_options()
        
        if self._target_dropdown.options:
            self._target_dropdown.value = self._target_dropdown.options[0].key
        self._target_dropdown.update()

    def _on_target_source_change(self, e: Any) -> None:
        """目标来源改变时切换显示"""
        self._sync_target_source_ui()

    def _sync_target_source_ui(self, update: bool = True) -> None:
        """同步目标来源 UI 显示"""
        is_preset = self._target_source_dropdown.value == "preset"
        self._target_dropdown.visible = is_preset
        self._custom_target_field.visible = not is_preset
        
        if update:
            self._target_dropdown.update()
            self._custom_target_field.update()

    def _start_search(self, e: Any = None) -> None:
        """开始搜索"""
        if self._searching:
            self.app.warn_dialog("搜索中", "当前正在搜索，请等待完成")
            return

        # 验证输入
        world_path = self._world_path_field.value
        if not world_path:
            self.app.warn_dialog("提示", "请先设置当前存档")
            return

        # 获取目标
        if self._target_source_dropdown.value == "preset":
            target = self._target_dropdown.value
        else:
            target = self._custom_target_field.value.strip()
        
        if not target:
            self.app.warn_dialog("提示", "请选择或输入目标 ID")
            return

        # 获取维度
        dimensions = []
        if self._dim_overworld.value:
            dimensions.append("overworld")
        if self._dim_nether.value:
            dimensions.append("nether")
        if self._dim_end.value:
            dimensions.append("end")
        
        if not dimensions:
            self.app.warn_dialog("提示", "请至少选择一个维度")
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
                search_type = self._search_type_dropdown.value
                results = self.service.search(
                    world_path=Path(world_path),
                    search_type=search_type,
                    target_id=target,
                    dimensions=dimensions,
                )
                
                self._search_results = results
                self._last_search_meta = {
                    "type": search_type,
                    "target": target,
                    "dimensions": dimensions,
                }
                
                # 更新 UI
                def _update_ui():
                    self._render_results()
                    self._status_title_text.value = f"✅ 搜索完成"
                    self._status_title_text.color = THEME.mc_grass
                    self._status_summary_text.value = f"找到 {len(results)} 个结果"
                    self._status_progress.visible = False
                    self._searching = False
                    self._search_btn.disabled = False
                    self._status_title_text.update()
                    self._status_summary_text.update()
                    self._status_progress.update()
                    self._search_btn.update()
                
                if hasattr(self.app.page, 'run_task'):
                    self.app.page.run_task(_update_ui)
                else:
                    _update_ui()
                    
            except Exception as ex:
                def _show_error():
                    self._status_title_text.value = "❌ 搜索失败"
                    self._status_title_text.color = THEME.error
                    self._status_summary_text.value = str(ex)
                    self._status_progress.visible = False
                    self._searching = False
                    self._search_btn.disabled = False
                    self._status_title_text.update()
                    self._status_summary_text.update()
                    self._status_progress.update()
                    self._search_btn.update()
                    self.app.handle_exception(ex, title="搜索失败")
                
                if hasattr(self.app.page, 'run_task'):
                    self.app.page.run_task(_show_error)
                else:
                    _show_error()

        threading.Thread(target=_search, daemon=True).start()

    def _render_results(self) -> None:
        """渲染搜索结果"""
        self._results_list.controls.clear()
        
        if not self._search_results:
            self._results_list.controls.append(
                placeholder(
                    icon="🔍",
                    title="未找到结果",
                    subtitle="尝试修改搜索条件",
                    height=200,
                )
            )
        else:
            displayed = min(len(self._search_results), self.DISPLAY_LIMIT)
            for i, result in enumerate(self._search_results[:displayed]):
                self._results_list.controls.append(self._build_result_row(i, result))
            
            if len(self._search_results) > displayed:
                self._results_list.controls.append(
                    ft.Text(
                        f"显示前 {displayed} 个结果，共 {len(self._search_results)} 个",
                        size=12,
                        color=THEME.warning,
                    )
                )
        
        self._results_list.update()

    def _build_result_row(self, index: int, result: SearchResult) -> ft.Container:
        """构建单个结果行"""
        dim_label = self.DIMENSION_LABELS.get(result.dimension, result.dimension)
        pos_text = f"({result.x}, {result.y}, {result.z})"
        
        return ft.Container(
            content=ft.Row([
                ft.Text(f"#{index + 1}", size=11, color=THEME.mc_gold, width=40),
                ft.Column([
                    ft.Text(result.target_id, size=12, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
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
                self.app.info_dialog("导出成功", f"已导出 {len(self._search_results)} 个结果到：\n{path}")
        except Exception as ex:
            self.app.handle_exception(ex, title="导出失败")
