"""Map Export View - 地图导出视图"""
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import flet as ft

from app.ui.theme import THEME
from app.ui.components.buttons import btn_primary, btn_ghost
from app.ui.components.fields import text_field, current_save_field
from app.ui.components.cards import card, section_title
from app.services.map_export_service import MapExportService, PIL_AVAILABLE

if TYPE_CHECKING:
    from app.application import Application


class MapExportView(ft.Column):
    """地图导出视图"""

    def __init__(self, app: "Application") -> None:
        super().__init__(spacing=20, scroll=ft.ScrollMode.AUTO)
        self.app = app
        
        # 检查依赖
        if not PIL_AVAILABLE:
            self._build_missing_dependency_ui()
            return
            
        self.service = MapExportService()
        self.expand = True

        # 状态
        self._exporting = False
        self._auto_output_path = ""

        # 配置选项
        self._world_path_field = current_save_field(
            hint_text="请通过侧边栏「设置当前存档」设置要导出的当前存档目录",
        )
        
        self._output_path_field = text_field(
            label="输出文件",
            hint_text="选择保存位置",
        )
        self._output_path_field.read_only = True

        self._map_type_dropdown = ft.Dropdown(
            label="地图类型",
            options=[
                ft.dropdown.Option("topview", "俯视图"),
                ft.dropdown.Option("terrain", "地形图（高度着色）"),
            ],
            value="topview",
            bgcolor=THEME.bg_secondary,
            border_color=THEME.border_subtle,
            color=THEME.text_primary,
        )

        self._scale_dropdown = ft.Dropdown(
            label="缩放比例",
            options=[
                ft.dropdown.Option("1", "1:1（原始大小）"),
                ft.dropdown.Option("2", "1:2（缩小一半）"),
                ft.dropdown.Option("4", "1:4（缩小四分之一）"),
                ft.dropdown.Option("8", "1:8（缩小八分之一）"),
            ],
            value="4",
            bgcolor=THEME.bg_secondary,
            border_color=THEME.border_subtle,
            color=THEME.text_primary,
        )

        # 结果显示
        self._result_text = ft.Text(
            "",
            size=13,
            color=THEME.text_secondary,
            selectable=True,
        )

        # 按钮
        self._select_output_btn = btn_ghost("💾 选择输出", on_click=self._select_output)
        self._export_btn = btn_primary("🗺️ 开始导出", on_click=self._start_export)

        # 构建 UI
        self._build_ui()

    def _build_missing_dependency_ui(self) -> None:
        """构建缺少依赖时的 UI"""
        self.spacing = 20
        self.expand = True
        
        error_card = card(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.ERROR_OUTLINE, size=48, color=THEME.error),
                            ft.Column(
                                [
                                    ft.Text(
                                        "缺少依赖库",
                                        size=20,
                                        weight=ft.FontWeight.BOLD,
                                        color=THEME.text_primary,
                                    ),
                                    ft.Text(
                                        "地图导出功能需要 Pillow 库支持",
                                        size=13,
                                        color=THEME.text_secondary,
                                    ),
                                ],
                                spacing=4,
                            ),
                        ],
                        spacing=16,
                    ),
                    ft.Divider(height=20, color=THEME.border_subtle),
                    ft.Text(
                        "请在命令行运行以下命令安装依赖：",
                        size=13,
                        color=THEME.text_secondary,
                    ),
                    ft.Container(
                        content=ft.Text(
                            "pip install Pillow",
                            size=13,
                            color=THEME.mc_grass,
                            font_family="monospace",
                            selectable=True,
                        ),
                        padding=12,
                        bgcolor=THEME.bg_secondary,
                        border_radius=8,
                    ),
                ],
                spacing=12,
            )
        )
        
        self.controls = [error_card]

    def _build_ui(self) -> None:
        """构建 UI"""
        # 标题
        header = ft.Row(
            [
                ft.Container(
                    content=ft.Text("🗺️", size=28, font_family="monospace"),
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
                            "地图导出",
                            size=24,
                            weight=ft.FontWeight.BOLD,
                            color=THEME.text_primary,
                        ),
                        ft.Text(
                            "将存档地图导出为 PNG 图片（俯视图/地形图）",
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
                    section_title("🗂️ 当前存档"),
                    self._world_path_field,
                    ft.Container(height=12),
                    section_title("💾 输出设置"),
                    ft.Row(
                        [self._output_path_field, self._select_output_btn],
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.END,
                    ),
                    ft.Container(height=12),
                    section_title("⚙️ 导出选项"),
                    ft.Row(
                        [self._map_type_dropdown, self._scale_dropdown],
                        spacing=12,
                    ),
                    ft.Container(height=12),
                    ft.Row(
                        [self._export_btn],
                        spacing=12,
                    ),
                ],
                spacing=12,
            )
        )

        # 结果卡片
        result_card = card(
            ft.Column(
                [
                    section_title("📋 导出结果"),
                    ft.Container(
                        content=self._result_text,
                        padding=12,
                        bgcolor=THEME.bg_secondary,
                        border_radius=8,
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
                        "• 俯视图：从上方俯瞰地图，显示地表最高方块颜色\n"
                        "• 地形图：根据高度着色，显示地形起伏\n"
                        "• 缩放比例：大型地图建议使用较大缩放比例以减小文件大小\n"
                        "• 导出时间取决于地图大小，请耐心等待",
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
            result_card,
            info_card,
        ]

        self._world_path_field.expand = True
        self._output_path_field.expand = True
        self._map_type_dropdown.expand = True
        self._scale_dropdown.expand = True

    def _select_output(self, e: ft.ControlEvent) -> None:
        """选择输出文件"""
        try:
            path = self.app.save_file(
                title="保存地图",
                default_ext=".png",
                file_types=[("PNG 图片", "*.png"), ("所有文件", "*.*")],
            )
            if path:
                self._output_path_field.value = path
                self._auto_output_path = ""
                self._output_path_field.update()
        except Exception as ex:
            self.app.error_dialog("错误", f"选择文件失败: {ex}")

    def _start_export(self, e: ft.ControlEvent) -> None:
        """开始导出"""
        if self._exporting:
            self.app.warn_dialog("提示", "导出正在进行中，请稍候")
            return

        world_path = self._world_path_field.value
        if not world_path:
            self.app.warn_dialog("提示", "请先通过侧边栏设置当前存档目录")
            return

        output_path = self._output_path_field.value
        if not output_path:
            self.app.warn_dialog("提示", "请先选择输出文件")
            return

        # 启动导出线程
        self._exporting = True
        self._export_btn.disabled = True
        self._export_btn.update()
        self._result_text.value = ""
        self._result_text.update()

        thread = threading.Thread(
            target=self._export_thread,
            args=(Path(world_path), Path(output_path)),
            daemon=True,
        )
        thread.start()

    def _export_thread(self, world_path: Path, output_path: Path) -> None:
        """导出线程"""
        try:
            async def _start():
                self.app.show_progress("正在导出地图...")
            self.app.page.run_task(_start)

            def progress_callback(value: float, msg: str) -> None:
                async def _progress(progress_value: float):
                    self.app.update_progress_with_task("导出地图", progress_value)
                self.app.page.run_task(_progress, value)

            def log_callback(msg: str, level: str) -> None:
                pass

            results = self.service.export_map(
                world_path=world_path,
                output_path=output_path,
                map_type=self._map_type_dropdown.value,
                scale=int(self._scale_dropdown.value),
                progress_callback=progress_callback,
                log_callback=log_callback,
            )

            async def _finish():
                if results['success']:
                    result_text = "导出完成！\n\n"
                    result_text += f"✓ 输出文件: {results['output_path']}\n"
                    result_text += f"✓ 图像尺寸: {results['dimensions'][0]} x {results['dimensions'][1]}\n"
                    result_text += f"✓ 处理区块: {results['chunks_processed']}"
                    self._result_text.value = result_text
                    self._result_text.update()
                    self.app.hide_progress()
                    self.app.info_dialog("完成", "地图导出完成！")
                else:
                    self._result_text.value = "导出失败，请查看日志"
                    self._result_text.update()
                    self.app.hide_progress()
                    self.app.error_dialog("错误", "地图导出失败")
                self._exporting = False
                self._export_btn.disabled = False
                self._export_btn.update()
            self.app.page.run_task(_finish)

        except Exception as ex:
            async def _error(error: Exception):
                self._result_text.value = f"导出失败: {error}"
                self._result_text.update()
                self.app.hide_progress()
                self.app.error_dialog("错误", f"导出失败: {error}")
                self._exporting = False
                self._export_btn.disabled = False
                self._export_btn.update()
            self.app.page.run_task(_error, ex)

    def on_save_selected(self, path: str) -> None:
        """统一入口设置当前存档回调"""
        try:
            self._world_path_field.value = path
            self._world_path_field.update()
            if not self._output_path_field.value:
                world_path = Path(path)
                self._output_path_field.value = str(world_path.parent / f"{world_path.name}_map.png")
                self._output_path_field.update()
        except Exception:
            pass
