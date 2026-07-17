"""Player tab mixin for ExplorerView."""
from pathlib import Path
from typing import Any, Dict, List, Union

import flet as ft

from app.models.nbt_edit import NbtChange
from app.ui.theme import THEME
from app.ui.components.buttons import btn_ghost
from app.ui.components.fields import text_field
from app.ui.components.cards import card
from app.ui.views.explorer.utils import safe_update
from app.ui.views.explorer.player_hud import PlayerHUDCard
from app.ui.views.explorer.equipment_preview import EquipmentPreview
from app.ui.views.explorer.inventory_grid import InventoryGrid
from app.ui.views.explorer.mixin_context import ExplorerMixinHost


class PlayerTabMixin(ExplorerMixinHost):
    """Build and handle Explorer player tab interactions."""

    def _build_player_tab(self) -> None:
        left = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO)
        left.controls.append(
            ft.Text(
                "选择玩家",
                size=14,
                weight=ft.FontWeight.BOLD,
                color=THEME.text_primary))
        self._player_dropdown = ft.Dropdown(
            options=[], on_select=self._on_player_selected,
            border_color=THEME.border_standard, text_size=13,
        )
        left.controls.append(self._player_dropdown)

        btn_row = ft.Row([
            btn_ghost("导入 usercache", height=30, on_click=self._import_usercache),
            btn_ghost("导入语言文件", height=30, on_click=self._import_language_file),
        ], spacing=8)
        left.controls.append(btn_row)

        self._player_hud = PlayerHUDCard()
        self._hud_card = card(self._player_hud, padding=15)
        left.controls.append(self._hud_card)

        self._equipment = EquipmentPreview(self.app.item, self.app.texture)
        self._equip_card = card(self._equipment, padding=15)
        left.controls.append(self._equip_card)

        self._build_player_edit_panel(left)

        right = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO)
        right.expand = True
        self._inventory = InventoryGrid(self.app.item, self.app.texture)
        right.controls.append(self._inventory)

        self._player_left_panel = ft.Container(content=left, width=340)
        self._player_right_panel = ft.Container(content=right, expand=True)
        self._player_layout = ft.Row(
            [self._player_left_panel, self._player_right_panel],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )
        self._tab_player.content = self._player_layout

    def _build_player_edit_panel(self, parent: ft.Column) -> None:
        self._player_edit_fields: Dict[str, ft.TextField] = {
            "Health": text_field(label="生命值", width=90, expand=False),
            "foodLevel": text_field(label="饥饿值", width=90, expand=False),
            "XpLevel": text_field(label="经验等级", width=90, expand=False),
            "XpTotal": text_field(label="总经验", width=90, expand=False),
            "Air": text_field(label="氧气", width=90, expand=False),
            "Pos.0": text_field(label="X", width=90, expand=False),
            "Pos.1": text_field(label="Y", width=90, expand=False),
            "Pos.2": text_field(label="Z", width=90, expand=False),
        }
        form = ft.Column([
            ft.Text("玩家数据编辑", size=16, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
            ft.Row([
                self._player_edit_fields["Health"],
                self._player_edit_fields["foodLevel"],
            ], spacing=8),
            ft.Row([
                self._player_edit_fields["XpLevel"],
                self._player_edit_fields["XpTotal"],
                self._player_edit_fields["Air"],
            ], spacing=8),
            ft.Text("坐标", size=12, color=THEME.text_secondary),
            ft.Row([
                self._player_edit_fields["Pos.0"],
                self._player_edit_fields["Pos.1"],
                self._player_edit_fields["Pos.2"],
            ], spacing=8),
            ft.Row([
                btn_ghost("刷新表单", height=30, on_click=self._refresh_player_edit_form),
            ], spacing=8),
        ], spacing=8)
        parent.controls.append(card(form, padding=15))

    def _get_tag_at_path(self, data: Any, path: List[Union[str, int]]) -> Any:
        node = data
        for part in path:
            node = node[part]
        return node

    def _refresh_player_edit_form(self, e: Any = None) -> None:
        try:
            if not self._current_player_data:
                return
            mapping = self._player_edit_mapping()
            for key, path in mapping.items():
                field = self._player_edit_fields.get(key)
                if not field:
                    continue
                try:
                    value = self._get_tag_at_path(
                        self._current_player_data, path)
                    field.value = self._tag_display_value(value)
                except Exception:
                    field.value = ""
                safe_update(field)
        except Exception as ex:
            self.app.handle_exception(ex, title="刷新玩家编辑表单失败")

    def _stage_player_edit_form(self, e: Any = None) -> None:
        try:
            if not self.current_uuid or not self._current_player_data:
                self.app.warn_dialog("提示", "请先选择玩家。")
                return
            staged = 0
            for key, path in self._player_edit_mapping().items():
                field = self._player_edit_fields.get(key)
                if not field or field.value is None or str(
                        field.value).strip() == "":
                    continue
                old_value = self._get_tag_at_path(
                    self._current_player_data, path)
                new_value = self._coerce_like_tag(str(field.value), old_value)
                if self._tag_display_value(
                        old_value) == self._tag_display_value(new_value):
                    continue
                self._nbt_stage_store.add(NbtChange(
                    target=self.current_uuid,
                    target_label=f"玩家 NBT: {self.current_uuid}",
                    format="nbt",
                    operation="set",
                    path=tuple(path),
                    display_path=".".join(str(part) for part in path),
                    old_value=old_value,
                    new_value=new_value,
                ))
                staged += 1
            self._update_nbt_stage_status()
            if staged:
                self.app.info_dialog(
                    "已暂存", f"已暂存 {staged} 个玩家数据修改，可到 NBT 页查看并提交。")
                self._switch_tab(5)
            else:
                self.app.info_dialog("提示", "没有检测到需要暂存的玩家数据修改。")
        except Exception as ex:
            self.app.handle_exception(ex, title="暂存玩家数据失败")

    def _refresh_player_list(self) -> None:
        if not self.world_session or not hasattr(self, "_player_dropdown"):
            return
        player_names = self.world_session.get_player_names()
        players = []
        for uuid, name in player_names.items():
            display = name or self.world_session._format_uuid_with_hyphens(
                uuid)
            formatted = self.world_session._format_uuid_with_hyphens(uuid)
            players.append((formatted, display))
        self._player_dropdown.options = [
            ft.dropdown.Option(v[0], v[1]) for v in players
        ]
        safe_update(self._player_dropdown)

        if players and not self.current_uuid:
            first_player_uuid = players[0][0]
            self._player_dropdown.value = first_player_uuid
            safe_update(self._player_dropdown)
            self._load_player_data(first_player_uuid)

    def _on_player_selected(self, e: Any) -> None:
        try:
            if not self.world_session or not e.control.value:
                return
            self._load_player_data(e.control.value)
        except Exception as ex:
            self.app.handle_exception(ex, title="选择玩家失败")

    def _load_player_data(self, uuid: str) -> None:
        try:
            if not self.world_session:
                return
            self.current_uuid = uuid
            self._current_chunk_target = None
            player_data = self.world_session.load_player_data(uuid)
            self._current_player_data = player_data
            if hasattr(self, "_player_hud"):
                self._player_hud.update_from_nbt(player_data)
            if hasattr(self, "_player_edit_fields"):
                self._refresh_player_edit_form()
            inv = self.world_session.get_player_inventory(uuid)
            if hasattr(self, "_inventory"):
                self._inventory.set_inventory(inv)
            if hasattr(self, "_equipment"):
                self._equipment.set_equipment(inv)
            nbt = self.world_session.load_player_nbt(uuid)
            self._current_nbt_target = uuid
            self._current_nbt_label = f"玩家 NBT: {uuid}"
            if hasattr(self, "_nbt_target_label"):
                self._nbt_target_label.value = self._current_nbt_label
                safe_update(self._nbt_target_label)
            if hasattr(self, "_nbt_tree"):
                self._nbt_tree.load_nbt(nbt)
        except Exception as e:
            self.app.handle_exception(e, title="加载玩家数据失败")

    def _import_usercache(self, e: Any = None) -> None:
        try:
            path = self.app.pick_file(
                title="选择 usercache.json",
                file_types=[("JSON 文件 (*.json)", "*.json")],
            )
            if path and self.world_session:
                imported = self.world_session.import_usercache(Path(path))
                if imported > 0:
                    self._refresh_player_list()
                    self.app.info_dialog("成功", f"成功导入 {imported} 个玩家名称。")
                else:
                    self.app.info_dialog("提示", "未能导入任何玩家名称。")
        except Exception as ex:
            self.app.handle_exception(ex, title="导入 usercache 失败")

    def _import_language_file(self, e: Any = None) -> None:
        try:
            path = self.app.pick_file(
                title="选择语言文件 (zh_cn.json 等)",
                file_types=[("JSON 文件 (*.json)", "*.json")],
            )
            if path:
                count = self.app.item.load_language_file(Path(path))
                if count > 0:
                    self.app.info_dialog(
                        "成功", f"成功导入 {count} 个物品/附魔名称。\n物品栏和装备预览将使用新名称。")
                    if self.current_uuid:
                        self._load_player_data(self.current_uuid)
                else:
                    self.app.info_dialog(
                        "提示",
                        "未能从文件中解析出有效的物品名称。\n\n"
                        "支持的格式：\n- Minecraft 语言文件 (item.minecraft.xxx)\n"
                        "- 直接 ID 映射 (minecraft:xxx)",
                    )
        except Exception as ex:
            self.app.handle_exception(ex, title="导入语言文件失败")

    def _player_edit_mapping(self) -> Dict[str, List[Union[str, int]]]:
        return {
            "Health": ["Health"],
            "foodLevel": ["foodLevel"],
            "XpLevel": ["XpLevel"],
            "XpTotal": ["XpTotal"],
            "Air": ["Air"],
            "Pos.0": ["Pos", 0],
            "Pos.1": ["Pos", 1],
            "Pos.2": ["Pos", 2],
        }
