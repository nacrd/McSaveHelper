"""World Info Panel component"""
import flet as ft
from typing import Callable, List, Mapping, Optional

from app.presenters.world_info_presenter import build_world_info_sections
from app.ui.theme import THEME, mc_border
from app.ui.icons import IconSet
from app.ui.components.cards import card, placeholder

from core.omni.world_session import WorldInfo
from app.ui.views.explorer.utils import safe_update


class WorldInfoPanel(ft.Column):
    """存档信息展示面板 - 分组卡片式布局"""

    def __init__(
        self,
        t_cb: Optional[Callable[..., str]] = None,
        on_backup_click: Optional[Callable] = None,
        on_restore_click: Optional[Callable] = None,
    ) -> None:
        super().__init__(spacing=12, scroll=ft.ScrollMode.AUTO)
        self.expand = True
        self._t = t_cb or (lambda k, d="", **kw: d)
        self._on_backup_click = on_backup_click
        self._on_restore_click = on_restore_click

        # 美化的占位符
        self._placeholder = ft.Container(
            content=ft.Column([
                ft.Text("📦", size=48, text_align=ft.TextAlign.CENTER),
                ft.Container(height=12),
                ft.Text(
                    "请先设置当前存档以查看信息",
                    size=16,
                    weight=ft.FontWeight.BOLD,
                    color=THEME.text_secondary,
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Container(height=8),
                ft.Text(
                    "通过侧边栏「设置当前存档」选择 Minecraft 世界目录",
                    size=13,
                    color=THEME.text_muted,
                    text_align=ft.TextAlign.CENTER,
                ),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding(left=20, right=20, top=40, bottom=40),
            bgcolor=THEME.bg_card,
            border=mc_border(2),
        )
        self.controls = [self._placeholder]

    def update_info(
        self,
        world_info: Optional[WorldInfo],
        stats: Optional[Mapping[str, object]] = None,
    ) -> None:
        """更新存档信息显示"""
        self.controls.clear()
        if world_info is None:
            self.controls.append(
                placeholder(
                    icon=IconSet.WARNING,
                    title="未找到存档信息",
                    subtitle="该目录可能不是有效的 Minecraft 世界存档",
                    height=200,
                )
            )
            safe_update(self)
            return

        for section in build_world_info_sections(world_info, stats, self._t):
            rows = [self._row(row.label, row.value) for row in section.rows]
            self.controls.append(self._section_card(section.title, rows))

        self.controls.append(self._build_backup_card())
        safe_update(self)

    def _build_backup_card(self) -> ft.Container:
        backup_buttons = ft.Row([
            ft.ElevatedButton(
                self._t("explorer.create_backup", "创建备份"),
                icon=ft.Icons.BACKUP,
                bgcolor=THEME.accent,
                color=THEME.text_invert,
                on_click=self._on_backup_click,
            ),
            ft.ElevatedButton(
                self._t("explorer.manage_backups", "管理恢复点"),
                icon=ft.Icons.RESTORE,
                bgcolor=THEME.bg_card,
                color=THEME.text_primary,
                on_click=self._on_restore_click,
            ),
        ], spacing=12)
        return card(
            ft.Column([
                ft.Text(
                    self._t("explorer.backup_title", "备份与恢复"),
                    size=15,
                    weight=ft.FontWeight.BOLD,
                    color=THEME.text_primary,
                ),
                ft.Divider(height=6, color=THEME.border_subtle),
                ft.Text(
                    self._t(
                        "explorer.backup_subtitle",
                        "创建恢复点或打开备份中心管理已有快照",
                    ),
                    size=12,
                    color=THEME.text_muted,
                ),
                ft.Container(height=8),
                backup_buttons,
            ], spacing=6),
            padding=14,
        )

    def _section_card(self, title: str, rows: List[ft.Row]) -> ft.Container:
        """创建分组信息卡片"""
        return card(
            ft.Column([
                ft.Text(title, size=15, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
                ft.Divider(height=6, color=THEME.border_subtle),
                *rows,
            ], spacing=6),
            padding=14,
        )

    def _row(self, label: str, value: str) -> ft.Row:
        """创建一行信息"""
        return ft.Row([
            ft.Text(label, size=13, color=THEME.text_secondary, width=130),
            ft.Text(str(value), size=13, color=THEME.text_primary, selectable=True, expand=True),
        ], vertical_alignment=ft.CrossAxisAlignment.START)
