"""Rendering helpers for NBT tree controls."""

import logging
from typing import Any, Callable, Dict, List

import flet as ft

from app.ui.theme import THEME, mc_border
from .parser import (
    detect_list_subtype,
    format_primitive,
    get_type_name,
    is_list_node,
    is_mapping_node,
    mapping_items,
)
from .type_info import MAX_CHILDREN, MAX_DEPTH, TYPE_INFO

logger = logging.getLogger(__name__)


class NbtTreeRenderer:
    """Builds Flet controls for NBT-like data."""

    def __init__(self, callbacks: Dict[str, Callable[..., Any]]) -> None:
        self.callbacks = callbacks

    def build_nodes(
        self,
        data: Any,
        path_prefix: str,
        depth: int,
        state: Dict[str, Any],
    ) -> List[ft.Control]:
        if not state["show_all"] and depth > MAX_DEPTH:
            return [ft.Text("  " * depth + "…（深度已达上限）", size=12, color=THEME.text_muted)]
        try:
            if is_mapping_node(data):
                return self._build_mapping_nodes(data, path_prefix, depth, state)
            if is_list_node(data):
                return self._build_list_nodes(data, path_prefix, depth, state)
        except Exception as ex:
            logger.debug("NBT 树渲染异常: %s", ex)
        return []

    def build_node(
        self,
        key: str,
        value: Any,
        path: str,
        depth: int,
        state: Dict[str, Any],
    ) -> ft.Control:
        type_name = get_type_name(value)
        icon, label, val_color = TYPE_INFO.get(type_name, ("❓", type_name, THEME.text_muted))
        is_highlighted = path.lower() in state["matches"]
        if is_mapping_node(value):
            return self._build_container_node(
                key, value, path, depth, state,
                icon, label, val_color, is_highlighted,
            )
        if is_list_node(value):
            return self._build_list_node(
                key, value, path, depth, state,
                icon, label, val_color, is_highlighted,
            )
        return self._build_primitive_node(
            key, value, path, depth, state,
            icon, label, val_color, is_highlighted,
        )

    def build_summary(self, stats: Dict[str, int], state: Dict[str, Any]) -> ft.Control:
        mode = "完整显示" if state["show_all"] else f"每层最多 {MAX_CHILDREN} 项"
        expand_state = "全部展开" if state["expand_all"] else "默认展开"
        if state["collapse_all"]:
            expand_state = "全部折叠"
        return ft.Container(
            content=ft.Row([
                ft.Text("NBT 概览", size=12, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
                self._pill(f"字段 {stats['fields']}"),
                self._pill(f"容器 {stats['containers']}"),
                self._pill(f"值 {stats['values']}"),
                ft.Container(expand=True),
                ft.Text(f"{expand_state} · {mode}", size=11, color=THEME.text_muted),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding(left=10, right=10, top=8, bottom=8),
            bgcolor=THEME.bg_secondary,
            border=mc_border(1),
        )

    def build_omitted_notice(self, omitted_count: int, depth: int) -> ft.Control:
        return ft.Container(
            content=ft.Text(
                f"还有 {omitted_count} 项未显示，"
                "点击上方“展开全部”可一次性显示全部 NBT。",
                size=12,
                color=THEME.text_muted,
            ),
            padding=ft.Padding(left=depth * 16 + 28, top=6, bottom=6, right=8),
            bgcolor=THEME.bg_secondary,
        )

    def _build_mapping_nodes(
        self,
        data: Any,
        path_prefix: str,
        depth: int,
        state: Dict[str, Any],
    ) -> List[ft.Control]:
        nodes: List[ft.Control] = []
        items = list(mapping_items(data))
        total_count = len(items)
        if not state["show_all"] and len(items) > MAX_CHILDREN:
            items = items[:MAX_CHILDREN]
        for key, value in items:
            child_path = f"{path_prefix}.{key}" if path_prefix else str(key)
            nodes.append(self.build_node(str(key), value, child_path, depth, state))
        if not state["show_all"] and total_count > MAX_CHILDREN:
            nodes.append(self.build_omitted_notice(total_count - MAX_CHILDREN, depth))
        return nodes

    def _build_list_nodes(
        self,
        data: Any,
        path_prefix: str,
        depth: int,
        state: Dict[str, Any],
    ) -> List[ft.Control]:
        nodes: List[ft.Control] = []
        length = len(data)
        show_count = length if state["show_all"] else min(length, MAX_CHILDREN)
        for i in range(show_count):
            nodes.append(self.build_node(f"[{i}]", data[i], f"{path_prefix}[{i}]", depth, state))
        if not state["show_all"] and length > MAX_CHILDREN:
            nodes.append(self.build_omitted_notice(length - MAX_CHILDREN, depth))
        return nodes

    def _build_container_node(
        self,
        key: str,
        value: Any,
        path: str,
        depth: int,
        state: Dict[str, Any],
        icon: str,
        label: str,
        color: str,
        highlighted: bool,
    ) -> ft.Control:
        item_count = len(value) if hasattr(value, "__len__") else 0
        title_controls = self._container_title(
            key, f"{item_count} 项", icon, label, color, highlighted,
        )
        self._add_edit_actions(title_controls, path, key, depth, is_list=False, state=state)
        children = self.build_nodes(value, path, depth + 1, state)
        return self._expansion(
            title_controls, children, depth, state, highlighted,
        )

    def _build_list_node(
        self,
        key: str,
        value: Any,
        path: str,
        depth: int,
        state: Dict[str, Any],
        icon: str,
        label: str,
        color: str,
        highlighted: bool,
    ) -> ft.Control:
        subtype = detect_list_subtype(value)
        subtitle = f"{len(value)} 项" + (f" · {subtype}" if subtype else "")
        title_controls = self._container_title(key, subtitle, icon, label, color, highlighted)
        self._add_edit_actions(title_controls, path, key, depth, is_list=True, state=state)
        children = self.build_nodes(value, path, depth + 1, state)
        return self._expansion(
            title_controls, children, depth, state, highlighted,
        )

    def _build_primitive_node(
        self,
        key: str,
        value: Any,
        path: str,
        depth: int,
        state: Dict[str, Any],
        icon: str,
        label: str,
        color: str,
        highlighted: bool,
    ) -> ft.Control:
        raw = format_primitive(value, get_type_name(value))
        display_val = raw if len(raw) <= 120 else raw[:117] + "…"
        key_color = THEME.warning if highlighted else THEME.text_primary
        controls = [
            self._type_badge(icon, label, color),
            ft.Text(
                key,
                size=13,
                weight=ft.FontWeight.BOLD,
                color=key_color,
            ),
            ft.Text(
                display_val,
                size=13,
                color=color,
                overflow=ft.TextOverflow.ELLIPSIS,
                expand=True,
            ),
        ]
        if state["editable"]:
            controls.append(ft.TextButton(
                "编辑",
                on_click=lambda e, p=path, v=value, t=get_type_name(value): (
                    self.callbacks["edit"](p, v, t)
                ),
            ))
            if depth > 0:
                controls.append(self._delete_button(path, key))
        return ft.Container(
            content=ft.Row(
                controls,
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding(
                left=depth * 16 + 28,
                top=2,
                bottom=2,
                right=8,
            ),
            bgcolor=self._row_bg(depth),
            border=self._left_border(THEME.border_subtle),
        )

    def _container_title(
        self,
        key: str,
        subtitle: str,
        icon: str,
        label: str,
        color: str,
        highlighted: bool,
    ) -> List[ft.Control]:
        key_color = THEME.warning if highlighted else THEME.text_primary
        return [
            self._type_badge(icon, label, color),
            ft.Text(
                key,
                size=13,
                weight=ft.FontWeight.BOLD,
                color=key_color,
            ),
            ft.Text(subtitle, size=11, color=THEME.text_secondary),
        ]

    def _add_edit_actions(
        self,
        controls: List[ft.Control],
        path: str,
        key: str,
        depth: int,
        is_list: bool,
        state: Dict[str, Any],
    ) -> None:
        if not state["editable"]:
            return
        controls.append(ft.Container(expand=True))
        controls.append(ft.IconButton(
            icon=ft.Icons.ADD,
            tooltip="新增列表项" if is_list else "新增字段",
            icon_size=14,
            on_click=lambda e, p=path, list_node=is_list: (
                self.callbacks["add"](p, list_node)
            ),
        ))
        if depth > 0:
            controls.append(self._delete_button(path, key))

    def _delete_button(self, path: str, key: str) -> ft.IconButton:
        return ft.IconButton(
            icon=ft.Icons.DELETE,
            tooltip="删除此字段",
            icon_size=14,
            icon_color=THEME.error,
            on_click=lambda e, p=path, k=key: self.callbacks["delete"](p, k),
        )

    def _expansion(
        self,
        title_controls: List[ft.Control],
        children: List[ft.Control],
        depth: int,
        state: Dict[str, Any],
        highlighted: bool,
    ) -> ft.ExpansionTile:
        return ft.ExpansionTile(
            title=ft.Row(
                title_controls,
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            controls=children,
            expanded=self._is_expanded(depth, state, highlighted),
            bgcolor=self._row_bg(depth),
            collapsed_bgcolor=self._row_bg(depth),
            tile_padding=ft.Padding(
                left=depth * 16,
                top=2,
                bottom=2,
                right=8,
            ),
            controls_padding=0,
            dense=True,
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
            content=ft.Row(
                [
                    ft.Text(icon, size=12),
                    ft.Text(
                        label,
                        size=10,
                        color=color,
                        font_family="monospace",
                    ),
                ],
                spacing=4,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding(left=5, right=6, top=2, bottom=2),
            bgcolor=THEME.bg_secondary,
            border=self._solid_border(THEME.border_subtle),
        )

    @staticmethod
    def _is_expanded(depth: int, state: Dict[str, Any], highlighted: bool) -> bool:
        if state["expand_all"]:
            return True
        if state["collapse_all"]:
            return False
        return depth < 1 or highlighted

    @staticmethod
    def _row_bg(depth: int) -> str:
        return THEME.bg_card if depth % 2 == 0 else THEME.bg_secondary

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
