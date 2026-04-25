"""Mappings view - UUID mapping management"""
import flet as ft
from typing import TYPE_CHECKING, Dict
from ui.constants import COLORS
from ui.widgets import UUIDMappingTable

if TYPE_CHECKING:
    from ui.app import App


class MappingsView(ft.Column):
    def __init__(self, app: "App"):
        super().__init__(expand=True, spacing=24, scroll=ft.ScrollMode.AUTO)
        self.app = app
        self._build()

    def _build(self):
        self.controls.clear()
        self.controls.append(
            ft.Text("🔗 UUID映射管理", size=22, weight=ft.FontWeight.BOLD, color=COLORS["text_primary"])
        )
        self.controls.append(
            ft.Text(
                "在此处管理自定义玩家名与UUID的映射关系。这些映射将用于批量迁移时的UUID替换。",
                size=13, color=COLORS["text_secondary"],
            )
        )
        self._table = UUIDMappingTable(
            mappings=self.app.custom_uuid_mappings,
            on_mappings_change=self.app._on_uuid_mappings_change,
        )
        self.controls.append(ft.Container(content=self._table, expand=True))
        self.controls.append(
            ft.Text(
                "提示：您可以通过\"导入名单\"批量导入映射，或手动添加每一行。\n"
                "映射数据会实时保存到配置文件，并在迁移时根据首页开关决定是否启用。",
                size=11, color=COLORS["text_muted"],
            )
        )

    def refresh_mappings(self):
        self._table.set_mappings(self.app.custom_uuid_mappings)
