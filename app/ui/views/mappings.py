"""Mappings View —— UUID 映射管理界面"""
import flet as ft
from typing import TYPE_CHECKING, Dict, Optional

from app.ui.theme import THEME
from app.ui.components.uuid_table import UUIDMappingTable

if TYPE_CHECKING:
    from app.application import Application


class MappingsView(ft.Column):
    """UUID 映射管理视图"""

    def __init__(self, app: "Application") -> None:
        super().__init__(spacing=24, scroll=ft.ScrollMode.AUTO)
        self.expand = True
        self.app: "Application" = app
        self._build()

    @property
    def _t(self):
        return self.app._t

    def _build(self) -> None:
        self.controls.clear()

        self.controls.append(ft.Text(
            self._t("mappings.title", "🔗 UUID映射管理"),
            size=22, weight=ft.FontWeight.BOLD, color=THEME.text_primary,
        ))
        self.controls.append(ft.Text(
            self._t("mappings.description",
                    "在此处管理自定义玩家名与UUID的映射关系。这些映射将用于批量迁移时的UUID替换。"),
            size=13, color=THEME.text_secondary,
        ))

        self._table: UUIDMappingTable = UUIDMappingTable(
            mappings=self.app.config.custom_uuid_mappings,
            on_mappings_change=self.app._on_uuid_mappings_change,
            on_import_click=self._on_import_click,
            on_export_click=self._on_export_click,
        )
        c = ft.Container(content=self._table)
        c.expand = True
        self.controls.append(c)

        self.controls.append(ft.Text(
            self._t("mappings.hint",
                    "提示：您可以通过\"导入名单\"批量导入映射，或手动添加每一行。\n"
                    "映射数据会实时保存到配置文件。"),
            size=11, color=THEME.text_muted,
        ))

    def refresh_mappings(self) -> None:
        self._table.set_mappings(self.app.config.custom_uuid_mappings)

    def _on_import_click(self) -> Optional[str]:
        """打开文件选择对话框，返回文件路径"""
        return self.app.pick_file(
            title="导入映射文件",
            file_types=[
                ("文本文件 (*.txt)", "*.txt"),
                ("CSV 文件 (*.csv)", "*.csv"),
                ("所有文件 (*.*)", "*.*"),
            ],
        )

    def _on_export_click(self, mappings: Dict[str, str]) -> Optional[str]:
        """打开保存对话框，返回文件路径"""
        if not mappings:
            return None
        return self.app.save_file(
            title="导出映射文件",
            default_ext=".txt",
            file_types=[
                ("文本文件 (*.txt)", "*.txt"),
                ("所有文件 (*.*)", "*.*"),
            ],
        )
