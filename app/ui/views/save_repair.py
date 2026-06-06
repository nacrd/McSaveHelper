"""Save Repair View - 存档修复视图"""
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import flet as ft

from app.ui.theme import THEME
from app.ui.components.buttons import btn_primary, btn_ghost
from app.ui.components.fields import text_field, checkbox
from app.ui.components.cards import card, section_title
from app.services.save_repair_service import SaveRepairService

if TYPE_CHECKING:
    from app.application import Application


class SaveRepairView(ft.Column):
    """存档修复视图"""

    def __init__(self, app: "Application") -> None:
        super().__init__()
        self.app = app
        self.service = SaveRepairService()
        self.spacing = 20
        self.expand = True

        # 状态
        self._repairing = False

        # 配置选项
        self._world_path_field = text_field(
            label="存档路径",
            hint_text="选择要修复的存档目录",
        )
        self._world_path_field.read_only = True
        self._fix_chunks_checkbox = checkbox("修复区块", value=True)
        self._fix_players_checkbox = checkbox("修复玩家数据", value=True)
        self._fix_level_dat_checkbox = checkbox("修复 level.dat", value=True)
        self._backup_checkbox = checkbox("创建备份（推荐）", value=True)

        # 结果显示
        self._result_text = ft.Text(
            "",
            size=13,
            color=THEME.text_secondary,
            selectable=True,
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
        self._repair_btn = btn_primary("🔧 开始修复", on_click=self._start_repair)

        # 构建 UI
        self._build_ui()

    def _build_ui(self) -> None:
        """构建 UI"""
        # 标题
        header = ft.Row(
            [
                ft.Container(
                    content=ft.Text("🔧", size=28, font_family="monospace"),
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
                            "存档修复",
                            size=24,
                            weight=ft.FontWeight.BOLD,
                            color=THEME.text_primary,
                        ),
                        ft.Text(
                            "修复损坏的区块、玩家数据、level.dat 错误",
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
                    section_title("⚙️ 修复选项"),
                    ft.Column(
                        [
                            self._fix_chunks_checkbox,
                            self._fix_players_checkbox,
                            self._fix_level_dat_checkbox,
                            self._backup_checkbox,
                        ],
                        spacing=8,
                    ),
                    ft.Container(height=12),
                    ft.Row(
                        [self._repair_btn],
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
                    section_title("📊 修复进度"),
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
                    section_title("📋 修复结果"),
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
                        "• 修复区块：检测并修复/移除损坏的区块数据\n"
                        "• 修复玩家数据：验证并修复玩家 .dat 文件\n"
                        "• 修复 level.dat：检查并从备份恢复 level.dat\n"
                        "• 建议在修复前创建备份，以防意外情况",
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

    def _select_world(self, e: ft.ControlEvent) -> None:
        """选择存档目录"""
        try:
            path = self.app.pick_directory()
            if path:
                self._world_path_field.value = path
                self._world_path_field.update()
        except Exception as ex:
            self.app.error_dialog("错误", f"选择目录失败: {ex}")

    def _start_repair(self, e: ft.ControlEvent) -> None:
        """开始修复"""
        if self._repairing:
            self.app.warn_dialog("提示", "修复正在进行中，请稍候")
            return

        world_path = self._world_path_field.value
        if not world_path:
            self.app.warn_dialog("提示", "请先选择存档目录")
            return

        # 启动修复线程
        self._repairing = True
        self._repair_btn.disabled = True
        self._repair_btn.update()
        self._result_text.value = ""
        self._result_text.update()

        thread = threading.Thread(
            target=self._repair_thread,
            args=(Path(world_path),),
            daemon=True,
        )
        thread.start()

    def _repair_thread(self, world_path: Path) -> None:
        """修复线程"""
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

            # 执行修复
            results = self.service.repair_world(
                world_path=world_path,
                fix_chunks=self._fix_chunks_checkbox.value,
                fix_players=self._fix_players_checkbox.value,
                fix_level_dat=self._fix_level_dat_checkbox.value,
                backup=self._backup_checkbox.value,
                progress_callback=progress_callback,
                log_callback=log_callback,
            )

            # 显示结果
            result_text = "修复完成！\n\n"
            result_text += f"✓ 区块修复: {results['chunks_fixed']}\n"
            result_text += f"✓ 区块移除: {results['chunks_removed']}\n"
            result_text += f"✓ 玩家修复: {results['players_fixed']}\n"
            result_text += f"✓ level.dat: {'已修复' if results['level_dat_fixed'] else '无需修复'}\n"
            
            if results['backup_path']:
                result_text += f"\n备份位置: {results['backup_path']}"

            self._result_text.value = result_text
            self._result_text.update()

            self.app.info_dialog("完成", "存档修复完成！")

        except Exception as ex:
            self._result_text.value = f"修复失败: {ex}"
            self._result_text.update()
            self.app.error_dialog("错误", f"修复失败: {ex}")

        finally:
            # 隐藏进度条
            self._progress_bar.visible = False
            self._progress_label.visible = False
            self._progress_bar.update()
            self._progress_label.update()

            # 恢复按钮
            self._repairing = False
            self._repair_btn.disabled = False
            self._repair_btn.update()
