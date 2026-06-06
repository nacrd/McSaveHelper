"""Entity/Block Search View - 实体/方块搜索视图"""
import threading
from pathlib import Path
from typing import TYPE_CHECKING, List

import flet as ft

from app.ui.theme import THEME
from app.ui.components.buttons import btn_primary, btn_ghost
from app.ui.components.fields import text_field, checkbox
from app.ui.components.cards import card, section_title
from app.services.entity_block_search_service import (
    EntityBlockSearchService,
    SearchResult,
)

if TYPE_CHECKING:
    from app.application import Application


class EntityBlockSearchView(ft.Column):
    """实体/方块搜索视图"""

    def __init__(self, app: "Application") -> None:
        super().__init__()
        self.app = app
        self.service = EntityBlockSearchService()
        self.spacing = 20
        self.expand = True
        self.scroll = ft.ScrollMode.AUTO

        # 状态
        self._searching = False
        self._search_results: List[SearchResult] = []

        # 配置选项
        self._world_path_field = text_field(
            label="存档路径",
            hint_text="选择要搜索的存档目录",
        )
        self._world_path_field.read_only = True

        self._search_type_dropdown = ft.Dropdown(
            label="搜索类型",
            options=[
                ft.dropdown.Option("entity", "🐾 实体"),
                ft.dropdown.Option("block", "🧱 方块"),
            ],
            value="entity",
            bgcolor=THEME.bg_secondary,
            border_color=THEME.border_subtle,
            color=THEME.text_primary,
        )
        self._search_type_dropdown.on_change = self._on_search_type_change

        # 实体/方块选择
        self._target_dropdown = ft.Dropdown(
            label="目标",
            options=self._get_entity_options(),
            bgcolor=THEME.bg_secondary,
            border_color=THEME.border_subtle,
            color=THEME.text_primary,
        )

        self._custom_target_field = text_field(
            label="自定义目标 ID",
            hint_text="例如: minecraft:villager",
        )

        # 维度选择
        self._dim_overworld = checkbox("主世界", value=True)
        self._dim_nether = checkbox("下界", value=True)
        self._dim_end = checkbox("末地", value=True)

        # 结果表格
        self._results_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("类型", weight=ft.FontWeight.BOLD, size=12)),
                ft.DataColumn(ft.Text("名称", weight=ft.FontWeight.BOLD, size=12)),
                ft.DataColumn(ft.Text("位置 (X, Y, Z)", weight=ft.FontWeight.BOLD, size=12)),
                ft.DataColumn(ft.Text("维度", weight=ft.FontWeight.BOLD, size=12)),
                ft.DataColumn(ft.Text("额外信息", weight=ft.FontWeight.BOLD, size=12)),
            ],
            rows=[],
            border=ft.border.all(1, THEME.border_subtle),
            border_radius=8,
            vertical_lines=ft.border.BorderSide(1, THEME.border_subtle),
            horizontal_lines=ft.border.BorderSide(1, THEME.border_subtle),
            heading_row_color=THEME.bg_secondary,
            heading_row_height=40,
            data_row_height=36,
        )

        self._result_count_text = ft.Text(
            "搜索结果: 0",
            size=13,
            weight=ft.FontWeight.BOLD,
            color=THEME.text_primary,
        )

        # 进度条
        self._progress_bar = ft.ProgressBar(
            value=0,
            color=THEME.mc_grass,
            bgcolor=THEME.bg_secondary,
            height=8,
        )
        self._progress_bar.visible = False

        self._progress_label = ft.Text(
            "",
            size=12,
            color=THEME.text_muted,
        )
        self._progress_label.visible = False

        # 按钮
        self._select_btn = btn_ghost("📁 选择存档", on_click=self._select_world)
        self._search_btn = btn_primary("🔍 开始搜索", on_click=self._start_search)
        self._export_btn = btn_ghost("💾 导出结果", on_click=self._export_results)
        self._export_btn.disabled = True

        # 构建 UI
        self._build_ui()

    def _get_entity_options(self) -> List[ft.dropdown.Option]:
        """获取实体选项列表"""
        options = []
        for entity in self.service.COMMON_ENTITIES:
            display_name = entity.replace("minecraft:", "").replace("_", " ").title()
            options.append(ft.dropdown.Option(entity, display_name))
        return options

    def _get_block_options(self) -> List[ft.dropdown.Option]:
        """获取方块选项列表"""
        options = []
        for block in self.service.COMMON_BLOCKS:
            display_name = block.replace("minecraft:", "").replace("_", " ").title()
            options.append(ft.dropdown.Option(block, display_name))
        return options

    def _on_search_type_change(self, e: ft.ControlEvent) -> None:
        """搜索类型改变时更新目标选项"""
        if self._search_type_dropdown.value == "entity":
            self._target_dropdown.options = self._get_entity_options()
            self._target_dropdown.label = "实体类型"
        else:
            self._target_dropdown.options = self._get_block_options()
            self._target_dropdown.label = "方块类型"
        self._target_dropdown.value = None
        self._target_dropdown.update()

    def _build_ui(self) -> None:
        """构建 UI"""
        # 标题
        header = ft.Row(
            [
                ft.Container(
                    content=ft.Text("🔍", size=28, font_family="monospace"),
                    width=56,
                    height=56,
                    alignment=ft.Alignment(0, 0),
                    bgcolor=THEME.mc_gold,
                    border=ft.Border(
                        left=ft.BorderSide(2, THEME.border_tertiary),
                        top=ft.BorderSide(2, THEME.border_tertiary),
                        right=ft.BorderSide(2, THEME.bg_secondary),
                        bottom=ft.BorderSide(2, THEME.bg_secondary),
                    ),
                ),
                ft.Column(
                    [
                        ft.Text(
                            "实体/方块搜索",
                            size=24,
                            weight=ft.FontWeight.BOLD,
                            color=THEME.text_primary,
                        ),
                        ft.Text(
                            "搜索特定实体（村民、苦力怕）或方块（钻石矿、下界合金）的位置",
                            size=12,
                            color=THEME.text_muted,
                        ),
                    ],
                    spacing=4,
                ),
            ],
            spacing=16,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        # 配置卡片
        config_card = card(
            ft.Column(
                [
                    section_title("🗂️ 存档选择"),
                    ft.Row(
                        [self._world_path_field, self._select_btn],
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.END,
                    ),
                    ft.Container(height=12),
                    section_title("🎯 搜索目标"),
                    ft.Row(
                        [self._search_type_dropdown, self._target_dropdown],
                        spacing=12,
                    ),
                    self._custom_target_field,
                    ft.Container(height=12),
                    section_title("🌍 维度选择"),
                    ft.Row(
                        [self._dim_overworld, self._dim_nether, self._dim_end],
                        spacing=16,
                    ),
                    ft.Container(height=12),
                    ft.Row(
                        [self._search_btn, self._export_btn],
                        spacing=12,
                    ),
                ],
                spacing=12,
            )
        )

        # 进度卡片
        progress_card = card(
            ft.Column(
                [
                    section_title("📊 搜索进度"),
                    self._progress_bar,
                    self._progress_label,
                ],
                spacing=12,
            )
        )

        # 结果卡片
        result_card = card(
            ft.Column(
                [
                    ft.Row(
                        [
                            section_title("📋 搜索结果"),
                            self._result_count_text,
                        ],
                        spacing=12,
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(
                        content=ft.Column(
                            [self._results_table],
                            scroll=ft.ScrollMode.AUTO,
                        ),
                        height=400,
                        bgcolor=THEME.bg_secondary,
                        border_radius=8,
                        padding=12,
                    ),
                ],
                spacing=12,
            )
        )

        # 使用说明
        info_card = card(
            ft.Column(
                [
                    section_title("ℹ️ 使用说明"),
                    ft.Text(
                        "• 选择预设的实体/方块，或输入自定义 ID（例如: minecraft:villager）\n"
                        "• 可以选择要搜索的维度（主世界、下界、末地）\n"
                        "• 搜索大型地图可能需要较长时间，请耐心等待\n"
                        "• 搜索完成后可以导出结果为文本文件",
                        size=12,
                        color=THEME.text_secondary,
                    ),
                ],
                spacing=12,
            )
        )

        self.controls = [
            header,
            ft.Container(height=8),
            config_card,
            progress_card,
            result_card,
            info_card,
        ]

        self._world_path_field.expand = True
        self._search_type_dropdown.expand = True
        self._target_dropdown.expand = True
        self._custom_target_field.expand = True

    def _select_world(self, e: ft.ControlEvent) -> None:
        """选择存档目录"""
        try:
            path = self.app.pick_directory()
            if path:
                self._world_path_field.value = path
                self._world_path_field.update()
        except Exception as ex:
            self.app.error_dialog("错误", f"选择目录失败: {ex}")

    def _start_search(self, e: ft.ControlEvent) -> None:
        """开始搜索"""
        if self._searching:
            self.app.warn_dialog("提示", "搜索正在进行中，请稍候")
            return

        world_path = self._world_path_field.value
        if not world_path:
            self.app.warn_dialog("提示", "请先选择存档目录")
            return

        # 获取目标
        target = self._custom_target_field.value or self._target_dropdown.value
        if not target:
            self.app.warn_dialog("提示", "请选择或输入搜索目标")
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

        # 启动搜索线程
        self._searching = True
        self._search_btn.disabled = True
        self._search_btn.update()

        thread = threading.Thread(
            target=self._search_thread,
            args=(Path(world_path), target, dimensions),
            daemon=True,
        )
        thread.start()

    def _search_thread(
        self,
        world_path: Path,
        target: str,
        dimensions: List[str],
    ) -> None:
        """搜索线程"""
        try:
            # 显示进度条
            self._progress_bar.visible = True
            self._progress_label.visible = True
            self._progress_bar.update()
            self._progress_label.update()

            def progress_callback(value: float, msg: str) -> None:
                self._progress_bar.value = value
                self._progress_label.value = msg
                try:
                    self._progress_bar.update()
                    self._progress_label.update()
                except Exception:
                    pass

            def log_callback(msg: str, level: str) -> None:
                pass  # 日志已通过 logger 处理

            # 执行搜索
            results = self.service.search(
                world_path=world_path,
                search_type=self._search_type_dropdown.value,
                target=target,
                dimensions=dimensions,
                progress_callback=progress_callback,
                log_callback=log_callback,
            )

            # 更新结果显示
            self._search_results = results
            self._update_results_table()

            if results:
                self.app.info_dialog("完成", f"搜索完成，找到 {len(results)} 个结果！")
            else:
                self.app.info_dialog("完成", "搜索完成，未找到匹配的结果")

        except Exception as ex:
            self.app.error_dialog("错误", f"搜索失败: {ex}")

        finally:
            # 隐藏进度条
            self._progress_bar.visible = False
            self._progress_label.visible = False
            self._progress_bar.update()
            self._progress_label.update()

            # 恢复按钮
            self._searching = False
            self._search_btn.disabled = False
            self._search_btn.update()
            
            # 启用导出按钮
            self._export_btn.disabled = len(self._search_results) == 0
            self._export_btn.update()

    def _update_results_table(self) -> None:
        """更新结果表格"""
        try:
            self._results_table.rows.clear()

            for result in self._search_results:
                # 格式化额外信息
                extra_info = ""
                if result.extra_info:
                    extra_info = ", ".join(
                        f"{k}: {v}" for k, v in result.extra_info.items()
                    )

                row = ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(result.result_type, size=11)),
                        ft.DataCell(ft.Text(result.name.split(":")[-1], size=11)),
                        ft.DataCell(
                            ft.Text(
                                f"{result.position[0]}, {result.position[1]}, {result.position[2]}",
                                size=11,
                                font_family="monospace",
                            )
                        ),
                        ft.DataCell(ft.Text(result.dimension, size=11)),
                        ft.DataCell(ft.Text(extra_info or "-", size=11)),
                    ]
                )
                self._results_table.rows.append(row)

            self._result_count_text.value = f"搜索结果: {len(self._search_results)}"
            self._result_count_text.update()
            self._results_table.update()

        except Exception as ex:
            print(f"更新表格失败: {ex}")

    def _export_results(self, e: ft.ControlEvent) -> None:
        """导出搜索结果"""
        if not self._search_results:
            self.app.warn_dialog("提示", "没有可导出的结果")
            return

        try:
            path = self.app.save_file(
                title="导出搜索结果",
                default_ext=".txt",
                file_types=[("文本文件", "*.txt"), ("所有文件", "*.*")],
            )
            if path:
                self.service.export_results_to_text(Path(path))
                self.app.info_dialog("完成", f"结果已导出到: {path}")
        except Exception as ex:
            self.app.error_dialog("错误", f"导出失败: {ex}")
