"""Edit, add and delete dialogs for NBT tree data."""

from typing import Any, Callable, Dict, List, Optional, Union

import flet as ft

from app.ui.theme import THEME
from app.ui.views.explorer.utils import safe_update
from .parser import (
    coerce_value,
    create_default_value,
    is_list_node,
    is_mapping_node,
    parse_path,
    raw_text,
)
from .type_info import FIELD_TYPE_OPTIONS


class NbtTreeEditor:
    """Handles mutation dialogs for NBTTreeView."""

    def __init__(self, owner: Any, on_stage_change: Optional[Callable]) -> None:
        self.owner = owner
        self.on_stage_change = on_stage_change

    def open_edit_dialog(self, path: str, value: Any, type_name: str) -> None:
        if not self.owner.page:
            return
        value_field, error_text, dialog = self._edit_dialog_controls(path, value, type_name)
        dialog.actions = [
            ft.TextButton("暂存", on_click=lambda e: self._stage_edit(path, value, type_name, value_field, error_text, dialog)),
            ft.TextButton("取消", on_click=lambda e: self._close(dialog)),
        ]
        self._show(dialog)

    def open_add_field_dialog(self, parent_path: str, is_list: bool) -> None:
        if not self.owner.page:
            return
        key_field, type_dropdown, value_field, error_text, dialog = self._add_dialog_controls(parent_path, is_list)
        dialog.actions = [
            ft.TextButton("新增", on_click=lambda e: self._add_field(parent_path, is_list, key_field, type_dropdown, value_field, error_text, dialog)),
            ft.TextButton("取消", on_click=lambda e: self._close(dialog)),
        ]
        self._show(dialog)

    def confirm_delete(self, path: str, key: str) -> None:
        if not self.owner.page:
            return
        dialog = ft.AlertDialog(
            title=ft.Text("确认删除", color=THEME.text_primary),
            content=ft.Text(f"确定要删除 {key} 吗？此操作将进入暂存区。", color=THEME.text_secondary),
            actions=[],
        )
        dialog.actions = [
            ft.TextButton("删除", on_click=lambda e: self._delete(path, dialog)),
            ft.TextButton("取消", on_click=lambda e: self._close(dialog)),
        ]
        self._show(dialog)

    def get_node_at_path(self, path_parts: List[Union[str, int]]) -> Any:
        if not path_parts:
            return self.owner._root_data
        node = self.owner._root_data
        for part in path_parts:
            if isinstance(part, int) and is_list_node(node):
                node = node[part]
            elif isinstance(part, str) and is_mapping_node(node):
                node = node[part]
            else:
                return None
        return node

    def set_value_at_path(self, path_parts: List[Union[str, int]], new_value: Any) -> Any:
        if self.owner._root_data is None:
            raise ValueError("未加载 NBT 数据")
        node = self.owner._root_data
        for part in path_parts[:-1]:
            node = node[part]
        old_value = node[path_parts[-1]]
        node[path_parts[-1]] = new_value
        return old_value

    def _edit_dialog_controls(self, path: str, value: Any, type_name: str) -> tuple:
        raw_value = raw_text(value, type_name)
        value_field = ft.TextField(label="新值", value=raw_value, multiline=type_name in ("IntArray", "ByteArray"), min_lines=1, max_lines=5, border_color=THEME.border_standard, text_size=13)
        error_text = ft.Text("", size=12, color=THEME.error)
        dialog = ft.AlertDialog(
            title=ft.Text(f"编辑 {path}", color=THEME.text_primary),
            content=ft.Column([ft.Text(f"类型: {type_name}", size=12, color=THEME.text_secondary), ft.Text(f"原值: {raw_value}", size=12, color=THEME.text_muted), value_field, error_text], tight=True, spacing=8),
            actions=[],
        )
        return value_field, error_text, dialog

    def _add_dialog_controls(self, parent_path: str, is_list: bool) -> tuple:
        parent = self.get_node_at_path(parse_path(parent_path))
        key_value = "" if not is_list else str(len(parent))
        key_field = ft.TextField(label="字段名/索引", value=key_value, border_color=THEME.border_standard, text_size=13, disabled=is_list)
        type_dropdown = ft.Dropdown(label="类型", options=[ft.dropdown.Option(v) for v in FIELD_TYPE_OPTIONS], value="String", border_color=THEME.border_standard, text_size=13)
        value_field = ft.TextField(label="初始值", value="", border_color=THEME.border_standard, text_size=13)
        error_text = ft.Text("", size=12, color=THEME.error)
        dialog = ft.AlertDialog(title=ft.Text(f"新增 {'列表项' if is_list else '字段'} 到 {parent_path}", color=THEME.text_primary), content=ft.Column([key_field, type_dropdown, value_field, error_text], tight=True, spacing=8), actions=[])
        return key_field, type_dropdown, value_field, error_text, dialog

    def _stage_edit(self, path: str, value: Any, type_name: str, value_field: ft.TextField, error_text: ft.Text, dialog: ft.AlertDialog) -> None:
        try:
            path_parts = parse_path(path)
            new_value = coerce_value(value_field.value or "", value, type_name)
            old_value = self.set_value_at_path(path_parts, new_value)
            self._notify(path_parts, old_value, new_value, path)
            self._close(dialog)
            self.owner._rebuild_tree()
        except Exception as ex:
            error_text.value = f"无法暂存: {ex}"
            safe_update(error_text)

    def _add_field(self, parent_path: str, is_list: bool, key_field: ft.TextField, type_dropdown: ft.Dropdown, value_field: ft.TextField, error_text: ft.Text, dialog: ft.AlertDialog) -> None:
        try:
            parent_parts = parse_path(parent_path)
            parent_node = self.get_node_at_path(parent_parts)
            new_value = create_default_value(type_dropdown.value, value_field.value or "")
            self._insert_value(parent_path, parent_parts, parent_node, key_field.value or "", new_value, is_list)
            self._close(dialog)
            self.owner._rebuild_tree()
        except Exception as ex:
            error_text.value = f"无法新增: {ex}"
            safe_update(error_text)

    def _insert_value(self, parent_path: str, parent_parts: List[Union[str, int]], parent_node: Any, key: str, new_value: Any, is_list: bool) -> None:
        if is_list:
            if not is_list_node(parent_node):
                raise ValueError("父节点不是列表")
            old_length = len(parent_node)
            parent_node.append(new_value)
            self._notify(parent_parts + [old_length], None, new_value, f"{parent_path}[{old_length}]")
            return
        if not is_mapping_node(parent_node):
            raise ValueError("父节点不是Compound")
        key = key.strip()
        if not key or key in parent_node:
            raise ValueError("字段名不能为空或字段已存在")
        parent_node[key] = new_value
        self._notify(parent_parts + [key], None, new_value, f"{parent_path}.{key}")

    def _delete(self, path: str, dialog: ft.AlertDialog) -> None:
        try:
            path_parts = parse_path(path)
            node = self.get_node_at_path(path_parts[:-1])
            if node is None:
                raise ValueError("找不到节点")
            old_value = node[path_parts[-1]]
            del node[path_parts[-1]]
            self._notify(path_parts, old_value, None, path)
            self._close(dialog)
            self.owner._rebuild_tree()
        except Exception as ex:
            self.owner.page.snack_bar = ft.SnackBar(ft.Text(f"删除失败: {ex}"))
            self.owner.page.snack_bar.open = True
            self.owner.page.update()

    def _notify(self, path_parts: List[Union[str, int]], old_value: Any, new_value: Any, path: str) -> None:
        if self.on_stage_change:
            self.on_stage_change(path_parts, old_value, new_value, path)

    def _show(self, dialog: ft.AlertDialog) -> None:
        self.owner.page.overlay.append(dialog)
        dialog.open = True
        self.owner.page.update()

    def _close(self, dialog: ft.AlertDialog) -> None:
        dialog.open = False
        # 从 overlay 中移除已关闭的对话框，避免内存泄漏
        if dialog in self.owner.page.overlay:
            self.owner.page.overlay.remove(dialog)
        self.owner.page.update()
