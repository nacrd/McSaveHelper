"""NBT Tree View component."""

import logging
from typing import Any, Callable, Dict, List, Optional, Set, Union

import flet as ft

from app.ui.components.cards import placeholder
from app.ui.theme import THEME
from app.ui.icons import IconSet
from app.ui.views.explorer.utils import safe_update
from .editor import NbtTreeEditor
from .exporter import export_json as export_nbt_json
from .parser import is_list_node, is_mapping_node, mapping_items
from .renderer import NbtTreeRenderer
from .search import collect_matches
from .type_info import MAX_CHILDREN, MAX_DEPTH, TYPE_INFO

logger = logging.getLogger(__name__)


class NBTTreeView(ft.Column):
    """NBT 树状视图 - 可展开/折叠的 NBT 数据浏览器"""

    MAX_DEPTH = MAX_DEPTH
    MAX_CHILDREN = MAX_CHILDREN
    _TYPE_INFO = TYPE_INFO

    def __init__(self, on_stage_change: Optional[Callable[[List[Union[str, int]], Any, Any, str], None]] = None) -> None:
        super().__init__(spacing=0, scroll=ft.ScrollMode.AUTO)
        self.expand = True
        self._root_data: Any = None
        self._search_query = ""
        self._matched_keys: Set[str] = set()
        self._expand_all = False
        self._collapse_all = False
        self._show_all_children = False
        self._on_stage_change = on_stage_change
        self._editable = True
        self._placeholder = placeholder(icon=IconSet.DOCUMENT, title="NBT 数据未加载", subtitle="请通过上方数据源选择玩家或 level.dat，或输入区块坐标加载", height=180)
        self.controls.append(self._placeholder)
        self._editor = NbtTreeEditor(self, on_stage_change)
        self._renderer = NbtTreeRenderer({"edit": self._open_edit_dialog, "add": self._open_add_field_dialog, "delete": self._confirm_delete})
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
        self._matched_keys = collect_matches(self._root_data, self._search_query) if self._root_data is not None else set()
        self._rebuild_tree()

    def get_modified_data(self) -> Any:
        return self._root_data

    def export_json(self, path: str) -> bool:
        """导出 NBT 数据为 JSON 文件。"""
        return export_nbt_json(self._root_data, path)

    def _rebuild_tree(self) -> None:
        self.controls.clear()
        if self._root_data is None:
            self.controls.append(self._placeholder)
            safe_update(self)
            return
        try:
            stats = self._collect_stats(self._root_data)
            self.controls.append(self._renderer.build_summary(stats, self._state()))
            nodes = self._renderer.build_nodes(self._root_data, "", depth=0, state=self._state())
            self.controls.extend(nodes or [ft.Text("（空 NBT 数据）", size=13, color=THEME.text_muted)])
        except Exception as e:
            self._show_parse_error(e)
        safe_update(self)

    def _collect_stats(self, data: Any) -> Dict[str, int]:
        stats = {"fields": 0, "containers": 0, "values": 0}

        def visit(node: Any) -> None:
            if is_mapping_node(node):
                stats["containers"] += 1
                for _, child in mapping_items(node):
                    stats["fields"] += 1
                    visit(child)
            elif is_list_node(node):
                stats["containers"] += 1
                stats["fields"] += len(node)
                for child in node:
                    visit(child)
            else:
                stats["values"] += 1
        try:
            visit(data)
        except Exception as ex:
            logger.debug("NBT 统计收集异常: %s", ex)
        return stats

    def _state(self) -> Dict[str, Any]:
        return {
            "show_all": self._show_all_children,
            "expand_all": self._expand_all,
            "collapse_all": self._collapse_all,
            "matches": self._matched_keys,
            "editable": self._editable,
        }

    def _show_parse_error(self, error: Exception) -> None:
        self.controls.append(ft.Column([
            ft.Text("解析 NBT 数据失败", size=13, weight=ft.FontWeight.BOLD, color=THEME.error),
            ft.Text(f"{type(error).__name__}: {str(error)}", size=11, color=THEME.text_secondary),
            ft.Text("可能原因：NBT 数据格式不兼容或数据结构异常", size=11, color=THEME.text_muted),
        ], spacing=4))

    def _open_edit_dialog(self, path: str, value: Any, type_name: str) -> None:
        self._editor.open_edit_dialog(path, value, type_name)

    def _open_add_field_dialog(self, parent_path: str, is_list: bool) -> None:
        self._editor.open_add_field_dialog(parent_path, is_list)

    def _confirm_delete(self, path: str, key: str) -> None:
        self._editor.confirm_delete(path, key)

    def _get_node_at_path(self, path_parts: List[Union[str, int]]) -> Any:
        return self._editor.get_node_at_path(path_parts)


__all__ = ["NBTTreeView"]
