"""NBT Tree View component"""
import flet as ft
import json
from typing import Any, Callable, Dict, List, Optional, Set, Union

from app.ui.theme import THEME, mc_border
from app.ui.components.cards import placeholder
from app.ui.views.explorer.utils import safe_update


class NBTTreeView(ft.Column):
    """NBT 树状视图 - 可展开/折叠的 NBT 数据浏览器"""

    MAX_DEPTH = 20
    MAX_CHILDREN = 500

    _TYPE_INFO = {
        "Compound":  ("📦", "Compound",  THEME.accent_light),
        "List":      ("📋", "List",      THEME.accent_light),
        "String":    ("🔤", "String",    THEME.terminal_green),
        "Int":       ("🔢", "Int",       THEME.terminal_cyan),
        "Long":      ("🔢", "Long",      THEME.terminal_cyan),
        "Byte":      ("🔵", "Byte",      THEME.terminal_blue),
        "Short":     ("🔢", "Short",     THEME.terminal_cyan),
        "Float":     ("📐", "Float",     THEME.terminal_purple),
        "Double":    ("📐", "Double",    THEME.terminal_purple),
        "IntArray":  ("🧮", "IntArray",  THEME.warning_light),
        "ByteArray": ("🧮", "ByteArray", THEME.warning_light),
        "str":       ("🔤", "String",    THEME.terminal_green),
        "int":       ("🔢", "Number",    THEME.terminal_cyan),
        "float":     ("📐", "Number",    THEME.terminal_purple),
        "bool":      ("🔘", "Boolean",   THEME.terminal_blue),
        "NoneType":  ("∅", "Null",      THEME.text_muted),
        "TAG_Compound": ("📦", "Compound", THEME.accent_light),
        "NBTFile":   ("📦", "Compound", THEME.accent_light),
        "TAG_List":  ("📋", "List",     THEME.accent_light),
        "TAG_String": ("🔤", "String",  THEME.terminal_green),
        "TAG_Int":   ("🔢", "Int",      THEME.terminal_cyan),
        "TAG_Long":  ("🔢", "Long",     THEME.terminal_cyan),
        "TAG_Byte":  ("🔵", "Byte",     THEME.terminal_blue),
        "TAG_Short": ("🔢", "Short",    THEME.terminal_cyan),
        "TAG_Float": ("📐", "Float",    THEME.terminal_purple),
        "TAG_Double": ("📐", "Double",  THEME.terminal_purple),
        "TAG_Int_Array": ("🧮", "IntArray", THEME.warning_light),
        "TAG_Byte_Array": ("🧮", "ByteArray", THEME.warning_light),
    }

    def __init__(
        self,
        on_stage_change: Optional[Callable[[List[Union[str, int]], Any, Any, str], None]] = None,
    ) -> None:
        super().__init__(spacing=0, scroll=ft.ScrollMode.AUTO)
        self.expand = True
        self._root_data: Any = None
        self._search_query: str = ""
        self._matched_keys: Set[str] = set()
        self._expand_all = False
        self._collapse_all = False
        self._show_all_children = False
        self._on_stage_change = on_stage_change
        self._editable = True
        self._placeholder = placeholder(
            icon="📜",
            title="NBT 数据未加载",
            subtitle="请通过上方数据源选择玩家或 level.dat，或输入区块坐标加载",
            height=180,
        )
        self.controls.append(self._placeholder)
        self._add_field_callbacks: List[Callable] = []
        self._delete_field_callbacks: List[Callable] = []

    def expand_all(self, show_all_children: bool = True) -> None:
        """展开整棵 NBT 树，可选择解除每层显示数量限制。"""
        self._expand_all = True
        self._collapse_all = False
        self._show_all_children = show_all_children
        self._rebuild_tree()

    def collapse_all(self) -> None:
        """折叠整棵 NBT 树并恢复默认按需显示模式。"""
        self._expand_all = False
        self._collapse_all = True
        self._show_all_children = False
        self._rebuild_tree()

    def reset_view(self) -> None:
        """恢复默认视图：仅展开顶层，保留大列表截断。"""
        self._expand_all = False
        self._collapse_all = False
        self._show_all_children = False
        self._rebuild_tree()

    def load_nbt(self, nbt_data: Any, editable: bool = True) -> None:
        self._root_data = nbt_data
        self._editable = editable
        self._search_query = ""
        self._matched_keys.clear()
        self._expand_all = False
        self._collapse_all = False
        self._show_all_children = False
        self._rebuild_tree()

    def search(self, query: str) -> None:
        self._search_query = query.strip().lower()
        self._matched_keys.clear()
        try:
            if self._search_query and self._root_data is not None:
                self._collect_matches(self._root_data, "")
        except Exception:
            pass
        self._rebuild_tree()

    def get_modified_data(self) -> Any:
        return self._root_data
    
    def export_json(self, path: str) -> bool:
        """导出 NBT 数据为 JSON 文件"""
        try:
            if self._root_data is None:
                return False
            
            def convert_to_serializable(obj):
                if hasattr(obj, 'value'):
                    return convert_to_serializable(obj.value)
                elif isinstance(obj, dict):
                    return {k: convert_to_serializable(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [convert_to_serializable(item) for item in obj]
                elif isinstance(obj, (int, float, str, bool, type(None))):
                    return obj
                else:
                    return str(obj)
            
            serializable_data = convert_to_serializable(self._root_data)
            
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(serializable_data, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception:
            return False

    def _rebuild_tree(self) -> None:
        self.controls.clear()
        if self._root_data is None:
            self.controls.append(self._placeholder)
            safe_update(self)
            return
        try:
            stats = self._collect_stats(self._root_data)
            self.controls.append(self._build_summary(stats))
            nodes = self._build_nodes(self._root_data, "", depth=0)
            if not nodes:
                self.controls.append(
                    ft.Text("（空 NBT 数据）", size=13, color=THEME.text_muted)
                )
            else:
                self.controls.extend(nodes)
        except Exception:
            self.controls.append(
                ft.Text("解析 NBT 数据失败", size=13, color=THEME.error)
            )
        safe_update(self)

    def _build_nodes(self, data: Any, path_prefix: str, depth: int) -> List:
        if not self._show_all_children and depth > self.MAX_DEPTH:
            return [ft.Text("  " * depth + "…（深度已达上限）", size=12, color=THEME.text_muted)]

        nodes: List = []
        try:
            if self._is_mapping_node(data):
                items = list(self._mapping_items(data))
                total_count = len(items)
                if not self._show_all_children and len(items) > self.MAX_CHILDREN:
                    items = items[:self.MAX_CHILDREN]
                for key, value in items:
                    child_path = f"{path_prefix}.{key}" if path_prefix else key
                    nodes.append(self._build_node(key, value, child_path, depth))
                if not self._show_all_children and total_count > self.MAX_CHILDREN:
                    nodes.append(
                        self._build_omitted_notice(total_count - self.MAX_CHILDREN, depth)
                    )
            elif self._is_list_node(data):
                length = len(data)
                show_count = length if self._show_all_children else min(length, self.MAX_CHILDREN)
                for i in range(show_count):
                    child_path = f"{path_prefix}[{i}]"
                    nodes.append(self._build_node(f"[{i}]", data[i], child_path, depth))
                if not self._show_all_children and length > self.MAX_CHILDREN:
                    nodes.append(
                        self._build_omitted_notice(length - self.MAX_CHILDREN, depth)
                    )
        except Exception:
            pass
        return nodes

    def _build_node(self, key: str, value: Any, path: str, depth: int) -> ft.Control:
        type_name = self._get_type_name(value)
        icon, label, val_color = self._TYPE_INFO.get(
            type_name, ("❓", type_name, THEME.text_muted)
        )
        is_highlighted = path.lower() in self._matched_keys

        if self._is_mapping_node(value):
            count = len(value) if hasattr(value, '__len__') else 0
            subtitle = f"{count} 项"
            title_controls = [
                self._type_badge(icon, label, val_color),
                ft.Text(key, size=13, weight=ft.FontWeight.BOLD,
                        color=THEME.warning if is_highlighted else THEME.text_primary),
                ft.Text(subtitle, size=11, color=THEME.text_secondary),
            ]
            if self._editable:
                title_controls.append(ft.Spacer())
                title_controls.append(ft.IconButton(
                    icon=ft.Icons.ADD,
                    tooltip="新增字段",
                    icon_size=14,
                    on_click=lambda e, p=path: self._open_add_field_dialog(p, is_list=False)
                ))
                if depth > 0:
                    title_controls.append(ft.IconButton(
                        icon=ft.Icons.DELETE,
                        tooltip="删除此字段",
                        icon_size=14,
                        icon_color=THEME.error,
                        on_click=lambda e, p=path, k=key: self._confirm_delete(p, k)
                    ))
            title_row = ft.Row(title_controls, spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)
            children = self._build_nodes(value, path, depth + 1)
            return ft.ExpansionTile(
                title=title_row,
                controls=children,
                expanded=self._is_expanded(depth, is_highlighted),
                bgcolor=self._row_bg(depth),
                collapsed_bgcolor=self._row_bg(depth),
                tile_padding=ft.Padding(left=depth * 16, top=2, bottom=2, right=8),
                controls_padding=0,
                dense=True,
            )
        elif self._is_list_node(value):
            length = len(value) if hasattr(value, '__len__') else 0
            list_type = self._detect_list_subtype(value)
            subtitle = f"{length} 项"
            if list_type:
                subtitle = f"{subtitle} · {list_type}"
            title_controls = [
                self._type_badge(icon, label, val_color),
                ft.Text(key, size=13, weight=ft.FontWeight.BOLD,
                        color=THEME.warning if is_highlighted else THEME.text_primary),
                ft.Text(subtitle, size=11, color=THEME.text_secondary),
            ]
            if self._editable:
                title_controls.append(ft.Spacer())
                title_controls.append(ft.IconButton(
                    icon=ft.Icons.ADD,
                    tooltip="新增列表项",
                    icon_size=14,
                    on_click=lambda e, p=path: self._open_add_field_dialog(p, is_list=True)
                ))
                if depth > 0:
                    title_controls.append(ft.IconButton(
                        icon=ft.Icons.DELETE,
                        tooltip="删除此列表",
                        icon_size=14,
                        icon_color=THEME.error,
                        on_click=lambda e, p=path, k=key: self._confirm_delete(p, k)
                    ))
            title_row = ft.Row(title_controls, spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)
            children = self._build_nodes(value, path, depth + 1)
            return ft.ExpansionTile(
                title=title_row,
                controls=children,
                expanded=self._is_expanded(depth, is_highlighted),
                bgcolor=self._row_bg(depth),
                collapsed_bgcolor=self._row_bg(depth),
                tile_padding=ft.Padding(left=depth * 16, top=2, bottom=2, right=8),
                controls_padding=0,
                dense=True,
            )
        else:
            raw = self._format_primitive(value, type_name)
            display_val = raw if len(raw) <= 120 else raw[:117] + "…"
            controls: List[ft.Control] = [
                self._type_badge(icon, label, val_color),
                ft.Text(key, size=13, weight=ft.FontWeight.BOLD,
                        color=THEME.warning if is_highlighted else THEME.text_primary),
                ft.Text(display_val, size=13, color=val_color,
                        overflow=ft.TextOverflow.ELLIPSIS, expand=True),
            ]
            if self._editable:
                controls.append(ft.TextButton("编辑", on_click=lambda e, p=path, v=value, t=type_name: self._open_edit_dialog(p, v, t)))
                if depth > 0:
                    controls.append(ft.IconButton(
                        icon=ft.Icons.DELETE,
                        tooltip="删除此字段",
                        icon_size=14,
                        icon_color=THEME.error,
                        on_click=lambda e, p=path, k=key: self._confirm_delete(p, k)
                    ))
            title_row = ft.Row(controls, spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)
            return ft.Container(
                content=title_row,
                padding=ft.Padding(left=depth * 16 + 28, top=2, bottom=2, right=8),
                bgcolor=self._row_bg(depth),
                border=self._left_border(THEME.border_subtle),
            )

    def _build_summary(self, stats: Dict[str, int]) -> ft.Control:
        mode = "完整显示" if self._show_all_children else f"每层最多 {self.MAX_CHILDREN} 项"
        expand_state = "全部展开" if self._expand_all else "默认展开"
        if self._collapse_all:
            expand_state = "全部折叠"
        return ft.Container(
            content=ft.Row([
                ft.Text("NBT 概览", size=12, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
                self._pill(f"字段 {stats['fields']}"),
                self._pill(f"容器 {stats['containers']}"),
                self._pill(f"值 {stats['values']}"),
                ft.Spacer(),
                ft.Text(f"{expand_state} · {mode}", size=11, color=THEME.text_muted),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding(left=10, right=10, top=8, bottom=8),
            bgcolor=THEME.bg_secondary,
            border=mc_border(1),
        )

    def _pill(self, text: str) -> ft.Control:
        return ft.Container(
            content=ft.Text(text, size=11, color=THEME.text_secondary),
            padding=ft.Padding(left=8, right=8, top=3, bottom=3),
            bgcolor=THEME.bg_card,
            border=self._solid_border(THEME.border_subtle),
        )

    def _type_badge(self, icon: str, label: str, color: str) -> ft.Control:
        return ft.Container(
            content=ft.Row([
                ft.Text(icon, size=12),
                ft.Text(label, size=10, color=color, font_family="monospace"),
            ], spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding(left=5, right=6, top=2, bottom=2),
            bgcolor=THEME.bg_secondary,
            border=self._solid_border(THEME.border_subtle),
        )

    @staticmethod
    def _solid_border(color: str, width: int = 1) -> ft.Border:
        side = ft.BorderSide(width, color)
        return ft.Border(left=side, top=side, right=side, bottom=side)

    @staticmethod
    def _left_border(color: str, width: int = 1) -> ft.Border:
        transparent = ft.BorderSide(0, ft.Colors.TRANSPARENT)
        return ft.Border(
            left=ft.BorderSide(width, color),
            top=transparent,
            right=transparent,
            bottom=transparent,
        )

    def _build_omitted_notice(self, omitted_count: int, depth: int) -> ft.Control:
        return ft.Container(
            content=ft.Text(
                f"还有 {omitted_count} 项未显示，点击上方“展开全部”可一次性显示全部 NBT。",
                size=12,
                color=THEME.text_muted,
            ),
            padding=ft.Padding(left=depth * 16 + 28, top=6, bottom=6, right=8),
            bgcolor=THEME.bg_secondary,
        )

    def _is_expanded(self, depth: int, is_highlighted: bool) -> bool:
        if self._expand_all:
            return True
        if self._collapse_all:
            return False
        return depth < 1 or is_highlighted

    @staticmethod
    def _row_bg(depth: int) -> str:
        return THEME.bg_card if depth % 2 == 0 else THEME.bg_secondary

    def _collect_stats(self, data: Any) -> Dict[str, int]:
        stats = {"fields": 0, "containers": 0, "values": 0}

        def visit(node: Any) -> None:
            if self._is_mapping_node(node):
                stats["containers"] += 1
                for _, child in self._mapping_items(node):
                    stats["fields"] += 1
                    visit(child)
            elif self._is_list_node(node):
                stats["containers"] += 1
                stats["fields"] += len(node)
                for child in node:
                    visit(child)
            else:
                stats["values"] += 1

        try:
            visit(data)
        except Exception:
            pass
        return stats

    def _open_edit_dialog(self, path: str, value: Any, type_name: str) -> None:
        if not self.page:
            return
        raw_value = self._raw_text(value, type_name)
        value_field = ft.TextField(
            label="新值",
            value=raw_value,
            multiline=type_name in ("IntArray", "ByteArray"),
            min_lines=1,
            max_lines=5,
            border_color=THEME.border_standard,
            text_size=13,
        )
        error_text = ft.Text("", size=12, color=THEME.error)
        dialog = ft.AlertDialog(
            title=ft.Text(f"编辑 {path}", color=THEME.text_primary),
            content=ft.Column([
                ft.Text(f"类型: {type_name}", size=12, color=THEME.text_secondary),
                ft.Text(f"原值: {raw_value}", size=12, color=THEME.text_muted),
                value_field,
                error_text,
            ], tight=True, spacing=8),
            actions=[],
        )

        def close_dialog(e: Any = None) -> None:
            dialog.open = False
            self.page.update()

        def stage_change(e: Any = None) -> None:
            try:
                path_parts = self._parse_path(path)
                new_value = self._coerce_value(value_field.value or "", value, type_name)
                old_value = self._set_value_at_path(path_parts, new_value)
                if self._on_stage_change:
                    self._on_stage_change(path_parts, old_value, new_value, path)
                dialog.open = False
                self.page.update()
                self._rebuild_tree()
            except Exception as ex:
                error_text.value = f"无法暂存: {ex}"
                safe_update(error_text)

        dialog.actions = [
            ft.TextButton("暂存", on_click=stage_change),
            ft.TextButton("取消", on_click=close_dialog),
        ]
        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    @staticmethod
    def _raw_text(value: Any, type_name: str) -> str:
        try:
            if type_name in ("IntArray", "ByteArray"):
                return json.dumps([int(x) for x in list(value)], ensure_ascii=False)
            if type_name in ("dict", "list", "bool", "NoneType"):
                return json.dumps(value, ensure_ascii=False)
            return str(getattr(value, "value", value))
        except Exception:
            return str(value)

    @staticmethod
    def _is_mapping_node(value: Any) -> bool:
        return isinstance(value, dict) or (
            hasattr(value, "keys") and hasattr(value, "__getitem__") and type(value).__name__ in ("NBTFile", "TAG_Compound")
        )

    @staticmethod
    def _mapping_items(value: Any) -> List[tuple]:
        if hasattr(value, "items"):
            return list(value.items())
        return [(key, value[key]) for key in value.keys()]

    @staticmethod
    def _is_list_node(value: Any) -> bool:
        return isinstance(value, list) or type(value).__name__ == "TAG_List"

    @staticmethod
    def _parse_path(path: str) -> List[Union[str, int]]:
        parts: List[Union[str, int]] = []
        current = ""
        i = 0
        while i < len(path):
            ch = path[i]
            if ch == ".":
                if current:
                    parts.append(current)
                    current = ""
                i += 1
                continue
            if ch == "[":
                if current:
                    parts.append(current)
                    current = ""
                end = path.index("]", i)
                parts.append(int(path[i + 1:end]))
                i = end + 1
                continue
            current += ch
            i += 1
        if current:
            parts.append(current)
        return parts

    def _set_value_at_path(self, path_parts: List[Union[str, int]], new_value: Any) -> Any:
        if self._root_data is None:
            raise ValueError("未加载 NBT 数据")
        node = self._root_data
        for part in path_parts[:-1]:
            node = node[part]
        last = path_parts[-1]
        old_value = node[last]
        node[last] = new_value
        return old_value

    @staticmethod
    def _coerce_value(raw: str, original: Any, type_name: str) -> Any:
        value_type = type(original)
        if type_name in ("Byte", "Short", "Int", "Long"):
            return value_type(int(raw.strip()))
        if type_name in ("Float", "Double"):
            return value_type(float(raw.strip()))
        if type_name == "String":
            return value_type(raw)
        if type_name == "TAG_String":
            return value_type(raw)
        if type_name in ("TAG_Byte", "TAG_Short", "TAG_Int", "TAG_Long"):
            return value_type(int(raw.strip()))
        if type_name in ("TAG_Float", "TAG_Double"):
            return value_type(float(raw.strip()))
        if type_name == "str":
            return raw
        if type_name == "int":
            return int(raw.strip())
        if type_name == "float":
            return float(raw.strip())
        if type_name == "bool":
            normalized = raw.strip().lower()
            if normalized in ("true", "1", "yes", "y", "是"):
                return True
            if normalized in ("false", "0", "no", "n", "否"):
                return False
            raise ValueError("布尔值必须是 true/false")
        if type_name == "NoneType":
            normalized = raw.strip().lower()
            if normalized in ("null", "none", ""):
                return None
            raise ValueError("空值必须是 null")
        if type_name in ("IntArray", "ByteArray"):
            parsed = json.loads(raw)
            if not isinstance(parsed, list):
                raise ValueError("数组值必须是 JSON 数组")
            return value_type([int(item) for item in parsed])
        try:
            return value_type(raw)
        except Exception:
            return raw

    @staticmethod
    def _get_type_name(value: Any) -> str:
        return type(value).__name__

    @staticmethod
    def _detect_list_subtype(lst: list) -> str:
        if not lst or len(lst) == 0:
            return ""
        return type(lst[0]).__name__ if lst else ""

    @staticmethod
    def _format_primitive(value: Any, type_name: str) -> str:
        try:
            if hasattr(value, 'value'):
                v = value.value
            else:
                v = value
            if type_name in ("IntArray", "ByteArray"):
                items = list(value)
                if len(items) <= 8:
                    return "[" + ", ".join(str(x) for x in items) + "]"
                return "[" + ", ".join(str(x) for x in items[:8]) + f", …] ({len(items)} 项)"
            if type_name == "String":
                s = str(v)
                return f'"{s}"'
            return str(v)
        except Exception:
            return str(value)

    def _open_add_field_dialog(self, parent_path: str, is_list: bool) -> None:
        if not self.page:
            return
        key_field = ft.TextField(
            label="字段名/索引",
            value="" if not is_list else str(len(self._get_node_at_path(self._parse_path(parent_path)))),
            border_color=THEME.border_standard,
            text_size=13,
            disabled=is_list,
        )
        type_dropdown = ft.Dropdown(
            label="类型",
            options=[
                ft.dropdown.Option("String"),
                ft.dropdown.Option("Int"),
                ft.dropdown.Option("Long"),
                ft.dropdown.Option("Byte"),
                ft.dropdown.Option("Short"),
                ft.dropdown.Option("Float"),
                ft.dropdown.Option("Double"),
                ft.dropdown.Option("Boolean"),
                ft.dropdown.Option("Compound"),
                ft.dropdown.Option("List"),
            ],
            value="String",
            border_color=THEME.border_standard,
            text_size=13,
        )
        value_field = ft.TextField(
            label="初始值",
            value="",
            border_color=THEME.border_standard,
            text_size=13,
        )
        error_text = ft.Text("", size=12, color=THEME.error)
        dialog = ft.AlertDialog(
            title=ft.Text(f"新增 {'列表项' if is_list else '字段'} 到 {parent_path}", color=THEME.text_primary),
            content=ft.Column([
                key_field,
                type_dropdown,
                value_field,
                error_text,
            ], tight=True, spacing=8),
            actions=[],
        )

        def close_dialog(e: Any = None) -> None:
            dialog.open = False
            self.page.update()

        def add_field(e: Any = None) -> None:
            try:
                path_parts = self._parse_path(parent_path)
                parent_node = self._get_node_at_path(path_parts)
                if parent_node is None:
                    raise ValueError("找不到父节点")
                if is_list:
                    if not self._is_list_node(parent_node):
                        raise ValueError("父节点不是列表")
                    new_value = self._create_default_value(type_dropdown.value, value_field.value)
                    old_length = len(parent_node)
                    parent_node.append(new_value)
                    if self._on_stage_change:
                        new_path_parts = path_parts + [old_length]
                        self._on_stage_change(new_path_parts, None, new_value, f"{parent_path}[{old_length}]")
                else:
                    if not self._is_mapping_node(parent_node):
                        raise ValueError("父节点不是Compound")
                    key = key_field.value.strip()
                    if not key:
                        raise ValueError("字段名不能为空")
                    if key in parent_node:
                        raise ValueError("字段已存在")
                    new_value = self._create_default_value(type_dropdown.value, value_field.value)
                    parent_node[key] = new_value
                    if self._on_stage_change:
                        new_path_parts = path_parts + [key]
                        self._on_stage_change(new_path_parts, None, new_value, f"{parent_path}.{key}")
                dialog.open = False
                self.page.update()
                self._rebuild_tree()
            except Exception as ex:
                error_text.value = f"无法新增: {ex}"
                safe_update(error_text)

        dialog.actions = [
            ft.TextButton("新增", on_click=add_field),
            ft.TextButton("取消", on_click=close_dialog),
        ]
        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    def _confirm_delete(self, path: str, key: str) -> None:
        if not self.page:
            return
        dialog = ft.AlertDialog(
            title=ft.Text("确认删除", color=THEME.text_primary),
            content=ft.Text(f"确定要删除 {key} 吗？此操作将进入暂存区。", color=THEME.text_secondary),
            actions=[],
        )

        def close_dialog(e: Any = None) -> None:
            dialog.open = False
            self.page.update()

        def do_delete(e: Any = None) -> None:
            try:
                path_parts = self._parse_path(path)
                node = self._get_node_at_path(path_parts[:-1])
                if node is None:
                    raise ValueError("找不到节点")
                last_part = path_parts[-1]
                old_value = node[last_part] if isinstance(last_part, (str, int)) else None
                if isinstance(last_part, int) and self._is_list_node(node):
                    del node[last_part]
                elif isinstance(last_part, str) and self._is_mapping_node(node):
                    del node[last_part]
                if self._on_stage_change:
                    self._on_stage_change(path_parts, old_value, None, path)
                dialog.open = False
                self.page.update()
                self._rebuild_tree()
            except Exception as ex:
                self.page.snack_bar = ft.SnackBar(ft.Text(f"删除失败: {ex}"))
                self.page.snack_bar.open = True
                self.page.update()

        dialog.actions = [
            ft.TextButton("删除", on_click=do_delete),
            ft.TextButton("取消", on_click=close_dialog),
        ]
        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    def _get_node_at_path(self, path_parts: List[Union[str, int]]) -> Any:
        if not path_parts:
            return self._root_data
        node = self._root_data
        for part in path_parts:
            if isinstance(part, int) and self._is_list_node(node):
                node = node[part]
            elif isinstance(part, str) and self._is_mapping_node(node):
                node = node[part]
            else:
                return None
        return node

    def _create_default_value(self, type_name: str, raw_value: str) -> Any:
        import nbtlib
        if type_name == "String":
            return nbtlib.String(raw_value)
        elif type_name == "Int":
            try:
                return nbtlib.Int(int(raw_value)) if raw_value else nbtlib.Int(0)
            except ValueError:
                return nbtlib.Int(0)
        elif type_name == "Long":
            try:
                return nbtlib.Long(int(raw_value)) if raw_value else nbtlib.Long(0)
            except ValueError:
                return nbtlib.Long(0)
        elif type_name == "Byte":
            try:
                return nbtlib.Byte(int(raw_value)) if raw_value else nbtlib.Byte(0)
            except ValueError:
                return nbtlib.Byte(0)
        elif type_name == "Short":
            try:
                return nbtlib.Short(int(raw_value)) if raw_value else nbtlib.Short(0)
            except ValueError:
                return nbtlib.Short(0)
        elif type_name == "Float":
            try:
                return nbtlib.Float(float(raw_value)) if raw_value else nbtlib.Float(0.0)
            except ValueError:
                return nbtlib.Float(0.0)
        elif type_name == "Double":
            try:
                return nbtlib.Double(float(raw_value)) if raw_value else nbtlib.Double(0.0)
            except ValueError:
                return nbtlib.Double(0.0)
        elif type_name == "Boolean":
            normalized = raw_value.strip().lower()
            return nbtlib.Byte(1 if normalized in ("true", "1", "yes", "y", "是") else 0)
        elif type_name == "Compound":
            return nbtlib.Compound({})
        elif type_name == "List":
            return []
        else:
            return raw_value

    def _collect_matches(self, data: Any, path_prefix: str) -> None:
        q = self._search_query
        try:
            if self._is_mapping_node(data):
                for key, value in self._mapping_items(data):
                    child_path = f"{path_prefix}.{key}" if path_prefix else key
                    if q in str(key).lower():
                        self._matched_keys.add(child_path.lower())
                    if self._is_mapping_node(value) or self._is_list_node(value):
                        self._collect_matches(value, child_path)
                    else:
                        raw = str(getattr(value, 'value', value)).lower()
                        if q in raw:
                            self._matched_keys.add(child_path.lower())
            elif self._is_list_node(data):
                for i, item in enumerate(data):
                    child_path = f"{path_prefix}[{i}]"
                    if self._is_mapping_node(item) or self._is_list_node(item):
                        self._collect_matches(item, child_path)
                    else:
                        raw = str(getattr(item, 'value', item)).lower()
                        if q in raw:
                            self._matched_keys.add(child_path.lower())
        except Exception:
            pass
