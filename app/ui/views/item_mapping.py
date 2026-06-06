"""自定义物品 ID 映射管理视图。"""
from pathlib import Path
from typing import TYPE_CHECKING, Dict

import flet as ft

from app.services.item_service import get_item_service
from app.ui.components.buttons import btn_ghost, btn_primary, btn_success, btn_danger
from app.ui.components.cards import card, section_title
from app.ui.components.fields import text_field
from app.ui.theme import THEME

if TYPE_CHECKING:
    from app.application import Application


class ItemMappingView(ft.Column):
    def __init__(self, app: "Application") -> None:
        super().__init__(spacing=18, scroll=ft.ScrollMode.AUTO)
        self.expand = True
        self.app = app
        self._service = get_item_service()
        self._build()

    def _build(self) -> None:
        self.controls.clear()
        self.controls.append(ft.Text("自定义物品映射", size=22, weight=ft.FontWeight.BOLD, color=THEME.text_primary))
        self.controls.append(ft.Text(
            "管理物品 ID 与显示名称的映射。支持导入 Minecraft 语言文件或自定义 JSON 映射。",
            size=12, color=THEME.text_muted,
        ))

        import_row = ft.Row([
            btn_primary("导入语言文件", width=140, on_click=self._import_lang),
            btn_primary("导入 JSON 映射", width=140, on_click=self._import_json),
            btn_ghost("导出当前映射", width=140, on_click=self._export),
        ], spacing=10)
        self.controls.append(card(import_row, padding=14))

        self._add_id_field = text_field(label="物品 ID (如 minecraft:diamond)", width=320, expand=False)
        self._add_name_field = text_field(label="显示名称", width=200, expand=False)
        add_row = ft.Row([
            self._add_id_field, self._add_name_field,
            btn_success("添加", width=80, on_click=self._add_mapping),
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        self.controls.append(card(ft.Column([section_title("手动添加"), add_row], spacing=8), padding=0))

        self._search_field = text_field(label="搜索物品 ID 或名称", on_change=self._on_search)
        self._table_container = ft.Container()
        self._table_container.expand = True
        self.controls.append(card(ft.Column([
            section_title("当前映射"),
            self._search_field,
            self._table_container,
        ], spacing=8), padding=0))

        self._render_table("")

    def _render_table(self, filter_text: str) -> None:
        mappings = self._service.get_custom_item_mappings()
        if not mappings:
            self._table_container.content = ft.Text("暂无自定义映射。可通过导入文件或手动添加。", size=12, color=THEME.text_muted)
            return

        rows = []
        filter_lower = filter_text.lower()
        for item_id, display_name in sorted(mappings.items()):
            if filter_lower and filter_lower not in item_id.lower() and filter_lower not in display_name.lower():
                continue
            rows.append(ft.DataRow(cells=[
                ft.DataCell(ft.Text(item_id, size=12, color=THEME.text_secondary, font_family="monospace")),
                ft.DataCell(ft.Text(display_name, size=12, color=THEME.text_primary)),
                ft.DataCell(ft.IconButton(
                    icon=ft.Icons.DELETE_OUTLINE,
                    icon_color=THEME.mc_redstone,
                    icon_size=18,
                    tooltip="删除",
                    on_click=lambda e, iid=item_id: self._delete_mapping(iid),
                )),
            ]))

        if not rows:
            self._table_container.content = ft.Text("没有匹配的映射。", size=12, color=THEME.text_muted)
            return

        self._table_container.content = ft.Container(
            content=ft.DataTable(
                columns=[
                    ft.DataColumn(ft.Text("物品 ID", size=12, weight=ft.FontWeight.BOLD, color=THEME.mc_gold)),
                    ft.DataColumn(ft.Text("显示名称", size=12, weight=ft.FontWeight.BOLD, color=THEME.mc_gold)),
                    ft.DataColumn(ft.Text("操作", size=12, weight=ft.FontWeight.BOLD, color=THEME.mc_gold)),
                ],
                rows=rows,
                heading_row_color=THEME.bg_secondary,
                data_row_color=THEME.bg_card,
                border=ft.border.all(1, THEME.border_subtle),
                column_spacing=20,
            ),
            height=min(400, 40 + len(rows) * 42),
        )

    def _on_search(self, e: ft.ControlEvent) -> None:
        self._render_table(e.control.value or "")
        try:
            self._table_container.update()
        except RuntimeError:
            pass

    def _add_mapping(self, e: ft.ControlEvent) -> None:
        item_id = (self._add_id_field.value or "").strip()
        display_name = (self._add_name_field.value or "").strip()
        if not item_id or not display_name:
            self.app.warn_dialog("提示", "物品 ID 和显示名称不能为空。")
            return
        self._service.set_item_mapping(item_id, display_name)
        self._add_id_field.value = ""
        self._add_name_field.value = ""
        self._render_table(self._search_field.value or "")
        self.update()

    def _delete_mapping(self, item_id: str) -> None:
        if item_id in self._service._name_map:
            del self._service._name_map[item_id]
        self._render_table(self._search_field.value or "")
        try:
            self._table_container.update()
        except RuntimeError:
            pass

    def _import_lang(self, e: ft.ControlEvent) -> None:
        try:
            path = self.app.pick_file(
                title="选择语言文件 (zh_cn.json 等)",
                file_types=[("JSON 文件 (*.json)", "*.json")],
            )
            if path:
                count = self._service.load_language_file(Path(path))
                self.app.info_dialog("成功", f"成功导入 {count} 个物品/附魔名称。")
                self._render_table(self._search_field.value or "")
                self.update()
        except Exception as ex:
            self.app.handle_exception(ex, title="导入语言文件失败")

    def _import_json(self, e: ft.ControlEvent) -> None:
        try:
            path = self.app.pick_file(
                title="选择 JSON 映射文件",
                file_types=[("JSON 文件 (*.json)", "*.json")],
            )
            if path:
                count = self._service.load_custom_mapping_file(Path(path))
                self.app.info_dialog("成功", f"成功导入 {count} 个映射。")
                self._render_table(self._search_field.value or "")
                self.update()
        except Exception as ex:
            self.app.handle_exception(ex, title="导入 JSON 映射失败")

    def _export(self, e: ft.ControlEvent) -> None:
        try:
            path = self.app.save_file(
                title="导出物品映射",
                default_ext=".json",
                file_types=[("JSON 文件 (*.json)", "*.json")],
            )
            if path:
                self._service.save_custom_mapping_file(Path(path))
                self.app.info_dialog("成功", f"映射已导出到 {path}")
        except Exception as ex:
            self.app.handle_exception(ex, title="导出映射失败")
