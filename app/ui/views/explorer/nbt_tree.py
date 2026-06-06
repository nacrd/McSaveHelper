"""NBT Tree View component"""
import flet as ft
import json
from typing import Any, Dict, List, Set

from app.ui.theme import THEME
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
    }

    def __init__(self) -> None:
        super().__init__(spacing=0, scroll=ft.ScrollMode.AUTO)
        self.expand = True
        self._root_data: Any = None
        self._search_query: str = ""
        self._matched_keys: Set[str] = set()
        self._placeholder = ft.Text(
            "请选择玩家以加载 NBT 数据", size=13, color=THEME.text_muted
        )
        self.controls.append(self._placeholder)

    def load_nbt(self, nbt_data: Any) -> None:
        self._root_data = nbt_data
        self._search_query = ""
        self._matched_keys.clear()
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
        if depth > self.MAX_DEPTH:
            return [ft.Text("  " * depth + "…（深度已达上限）", size=12, color=THEME.text_muted)]

        nodes: List = []
        try:
            if isinstance(data, dict):
                items = list(data.items())
                if len(items) > self.MAX_CHILDREN:
                    items = items[:self.MAX_CHILDREN]
                for key, value in items:
                    child_path = f"{path_prefix}.{key}" if path_prefix else key
                    nodes.append(self._build_node(key, value, child_path, depth))
                if len(data) > self.MAX_CHILDREN:
                    nodes.append(
                        ft.Text(
                            "  " * depth + f"…（省略 {len(data) - self.MAX_CHILDREN} 项）",
                            size=12, color=THEME.text_muted,
                        )
                    )
            elif isinstance(data, list):
                length = len(data)
                show_count = min(length, self.MAX_CHILDREN)
                for i in range(show_count):
                    child_path = f"{path_prefix}[{i}]"
                    nodes.append(self._build_node(f"[{i}]", data[i], child_path, depth))
                if length > self.MAX_CHILDREN:
                    nodes.append(
                        ft.Text(
                            "  " * depth + f"…（省略 {length - self.MAX_CHILDREN} 项）",
                            size=12, color=THEME.text_muted,
                        )
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

        if isinstance(value, dict):
            count = len(value) if hasattr(value, '__len__') else 0
            subtitle = f"{count} 项"
            title_row = ft.Row([
                ft.Text(icon, size=13),
                ft.Text(key, size=13, weight=ft.FontWeight.BOLD,
                        color=THEME.warning if is_highlighted else THEME.text_primary),
                ft.Text(f"({label})", size=11, color=THEME.text_muted),
                ft.Text(subtitle, size=11, color=THEME.text_secondary),
            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)
            children = self._build_nodes(value, path, depth + 1)
            return ft.ExpansionTile(
                title=title_row,
                controls=children,
                expanded=(depth < 1 or is_highlighted),
                bgcolor=ft.Colors.TRANSPARENT,
                collapsed_bgcolor=ft.Colors.TRANSPARENT,
                tile_padding=ft.Padding(left=depth * 16, top=2, bottom=2, right=8),
                controls_padding=0,
                dense=True,
            )
        elif isinstance(value, list):
            length = len(value) if hasattr(value, '__len__') else 0
            list_type = self._detect_list_subtype(value)
            subtitle = f"{length} 项"
            type_hint = f"<{list_type}>" if list_type else ""
            title_row = ft.Row([
                ft.Text(icon, size=13),
                ft.Text(key, size=13, weight=ft.FontWeight.BOLD,
                        color=THEME.warning if is_highlighted else THEME.text_primary),
                ft.Text(f"({label}{type_hint})", size=11, color=THEME.text_muted),
                ft.Text(subtitle, size=11, color=THEME.text_secondary),
            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)
            children = self._build_nodes(value, path, depth + 1)
            return ft.ExpansionTile(
                title=title_row,
                controls=children,
                expanded=(depth < 1 or is_highlighted),
                bgcolor=ft.Colors.TRANSPARENT,
                collapsed_bgcolor=ft.Colors.TRANSPARENT,
                tile_padding=ft.Padding(left=depth * 16, top=2, bottom=2, right=8),
                controls_padding=0,
                dense=True,
            )
        else:
            raw = self._format_primitive(value, type_name)
            display_val = raw if len(raw) <= 120 else raw[:117] + "…"
            title_row = ft.Row([
                ft.Text(icon, size=13),
                ft.Text(key, size=13, weight=ft.FontWeight.BOLD,
                        color=THEME.warning if is_highlighted else THEME.text_primary),
                ft.Text(f"({label})", size=11, color=THEME.text_muted),
                ft.Text(display_val, size=13, color=val_color,
                        overflow=ft.TextOverflow.ELLIPSIS, expand=True),
            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)
            return ft.Container(
                content=title_row,
                padding=ft.Padding(left=depth * 16 + 28, top=2, bottom=2, right=8),
            )

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

    def _collect_matches(self, data: Any, path_prefix: str) -> None:
        q = self._search_query
        try:
            if isinstance(data, dict):
                for key, value in data.items():
                    child_path = f"{path_prefix}.{key}" if path_prefix else key
                    if q in key.lower():
                        self._matched_keys.add(child_path.lower())
                    if isinstance(value, (dict, list)):
                        self._collect_matches(value, child_path)
                    else:
                        raw = str(getattr(value, 'value', value)).lower()
                        if q in raw:
                            self._matched_keys.add(child_path.lower())
            elif isinstance(data, list):
                for i, item in enumerate(data):
                    child_path = f"{path_prefix}[{i}]"
                    if isinstance(item, (dict, list)):
                        self._collect_matches(item, child_path)
                    else:
                        raw = str(getattr(item, 'value', item)).lower()
                        if q in raw:
                            self._matched_keys.add(child_path.lower())
        except Exception:
            pass
