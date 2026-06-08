"""Chunk Operations - 负责区块相关的操作（对象、方块查询/替换）"""
from typing import Any, Dict, List

import flet as ft

from app.ui.theme import THEME
from app.ui.components.cards import placeholder
from app.ui.views.explorer.utils import safe_update
from app.ui.views.explorer.explorer_helpers import extract_chunk_objects


class ChunkOperations:
    """区块操作管理器 - 处理区块对象渲染、方块查询和替换"""

    def __init__(self, context: Any):
        """
        Args:
            context: 上下文对象，需要提供区块相关字段和方法
        """
        self.ctx = context

    # ==================== 区块对象操作 ====================

    def render_chunk_objects(self, chunk_data: Any) -> None:
        """渲染区块对象列表"""
        try:
            self.ctx._chunk_objects_list.controls.clear()
            self.ctx._last_chunk_objects = extract_chunk_objects(chunk_data)
            self.render_chunk_object_rows(self.ctx._last_chunk_objects)
        except Exception as ex:
            self.ctx.app.handle_exception(ex, title="渲染区块对象失败")

    def on_chunk_object_filter(self, e: Any) -> None:
        """过滤区块对象"""
        query = (e.control.value or "").strip().lower()
        if not query:
            self.render_chunk_object_rows(self.ctx._last_chunk_objects)
            return
        filtered = [
            obj for obj in self.ctx._last_chunk_objects
            if query in obj["title"].lower() or query in obj["subtitle"].lower()
        ]
        self.render_chunk_object_rows(filtered)

    def render_chunk_object_rows(self, objects: List[Dict[str, Any]]) -> None:
        """渲染区块对象行"""
        try:
            self.ctx._chunk_objects_list.controls.clear()
            if not objects:
                self.ctx._chunk_objects_list.controls.append(
                    placeholder(
                        icon="📦",
                        title="未发现实体或方块实体",
                        subtitle="请先加载区块，区块内的实体和容器将在此列出",
                        height=100,
                    )
                )
            else:
                for obj in objects[:120]:
                    self.ctx._chunk_objects_list.controls.append(ft.Container(
                        content=ft.Row([
                            ft.Text(obj["icon"], size=16, width=28),
                            ft.Column([
                                ft.Text(obj["title"], size=12, color=THEME.text_primary),
                                ft.Text(obj["subtitle"], size=11, color=THEME.text_muted),
                            ], spacing=2, expand=True),
                            ft.TextButton(
                                "查看",
                                on_click=lambda e, data=obj["data"], title=obj["title"]:
                                    self.show_chunk_object(data, title)
                            ),
                        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        padding=ft.Padding(left=6, right=6, top=4, bottom=4),
                        bgcolor=THEME.bg_card,
                    ))
                if len(objects) > 120:
                    self.ctx._chunk_objects_list.controls.append(
                        ft.Text(
                            f"已显示前 120 个对象，剩余 {len(objects) - 120} 个",
                            size=12,
                            color=THEME.text_muted
                        )
                    )
            safe_update(self.ctx._chunk_objects_list)
        except Exception as ex:
            self.ctx.app.handle_exception(ex, title="渲染区块对象失败")

    def show_chunk_object(self, data: Any, title: str) -> None:
        """显示区块对象的 NBT"""
        if hasattr(
                self.ctx,
                "_current_chunk_target") and self.ctx._current_chunk_target:
            self.ctx._current_chunk_object = {
                "data": data,
                "title": title,
            }
            self.ctx._current_nbt_label = f"区块对象: {title}"
            self.ctx._current_edit_format = "chunk"
        else:
            self.ctx._current_nbt_label = f"区块对象只读: {title}"
            self.ctx._current_edit_format = "chunk_readonly"
        self.ctx._nbt_target_label.value = self.ctx._current_nbt_label
