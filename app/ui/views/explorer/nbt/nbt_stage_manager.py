"""NBT Stage Manager - 负责管理 NBT 编辑的暂存区"""
from typing import Any, Dict, List, Tuple, Union

import flet as ft

from app.ui.theme import THEME
from app.ui.icons import IconSet
from app.ui.components.cards import placeholder
from app.ui.views.explorer.utils import safe_update
from app.ui.views.explorer.explorer_helpers import format_stage_value


class NbtStageManager:
    """NBT 暂存管理器 - 管理待提交的 NBT 变更"""

    def __init__(self, context: Any):
        """
        Args:
            context: 上下文对象，需要提供 _staged_nbt_changes, _nbt_stage_status 等属性
        """
        self.ctx = context

    # ==================== 暂存操作 ====================

    def stage_change(
        self,
        path_parts: List[Union[str, int]],
        old_value: Any,
        new_value: Any,
        display_path: str,
    ) -> None:
        """暂存一个 NBT 修改"""
        try:
            if self.ctx._current_nbt_target is None:
                self.ctx.app.warn_dialog("提示", "请先加载要编辑的 NBT 数据。")
                return

            change = {
                "target": self.ctx._current_nbt_target,
                "target_label": self.ctx._current_nbt_label,
                "format": self.ctx._current_edit_format,
                "operation": "delete" if new_value is None else "add" if old_value is None else "set",
                "path": path_parts,
                "display_path": display_path,
                "old_value": old_value,
                "new_value": new_value,
            }
            self.ctx._staged_nbt_changes.append(change)
            self.update_stage_status()
            self.ctx.app.log(f"已暂存 NBT 修改: {display_path}", "QUEUE")
        except Exception as ex:
            self.ctx.app.handle_exception(ex, title="暂存 NBT 修改失败")

    def unstage_change(self, index: int) -> None:
        """撤销一个暂存的变更"""
        try:
            if index < 0 or index >= len(self.ctx._staged_nbt_changes):
                return
            self.ctx._staged_nbt_changes.pop(index)
            self.update_stage_status()
            # 重新加载当前目标以反映撤销
            if hasattr(self.ctx, '_data_loader'):
                self.ctx._data_loader.reload_current_nbt_target()
        except Exception as ex:
            self.ctx.app.handle_exception(ex, title="撤销暂存变更失败")

    def discard_all_changes(self, e: Any = None) -> None:
        """丢弃所有暂存的变更"""
        try:
            if not self.ctx._staged_nbt_changes:
                self.ctx.app.info_dialog("提示", "暂存区没有变更。")
                return
            self.ctx._staged_nbt_changes.clear()
            self.update_stage_status()
            # 重新加载当前目标
            if hasattr(self.ctx, '_data_loader'):
                self.ctx._data_loader.reload_current_nbt_target()
            self.ctx.app.info_dialog("已丢弃", "已丢弃暂存区中的 NBT 变更，并重新加载当前 NBT 数据。")
        except Exception as ex:
            self.ctx.app.handle_exception(ex, title="丢弃 NBT 变更失败")

    # ==================== 状态更新 ====================

    def update_stage_status(self) -> None:
        """更新暂存区状态显示"""
        try:
            count = len(self.ctx._staged_nbt_changes)
            self.ctx._nbt_stage_status.value = f"暂存区: {count} 个变更"
            self.ctx._nbt_stage_status.color = THEME.warning if count else THEME.text_muted
            self.render_stage_list()
            safe_update(self.ctx._nbt_stage_status)
        except Exception as ex:
            self.ctx.app.handle_exception(ex, title="更新暂存区状态失败")

    def render_stage_list(self) -> None:
        """渲染暂存区变更列表"""
        try:
            self.ctx._nbt_stage_list.controls.clear()
            if not self.ctx._staged_nbt_changes:
                self.ctx._nbt_stage_list.controls.append(
                    placeholder(
                        icon=IconSet.CLIPBOARD,
                        title="暂无暂存变更",
                        subtitle="对 NBT 树中的字段进行编辑后，变更会暂存在此处等待提交",
                        height=120,
                    )
                )
            else:
                # 按目标文件分组
                grouped_changes: Dict[str, List[Tuple[int, Dict]]] = {}
                for index, change in enumerate(self.ctx._staged_nbt_changes):
                    target_key = str(change["target"])
                    if target_key not in grouped_changes:
                        grouped_changes[target_key] = []
                    grouped_changes[target_key].append((index, change))

                # 为每个分组创建一个卡片
                for target_key, changes in grouped_changes.items():
                    first_change = changes[0][1]
                    target_label = first_change["target_label"]

                    group_header = ft.Row([
                        ft.Text("📁", size=14, color=THEME.accent),
                        ft.Text(
                            target_label,
                            size=13,
                            weight=ft.FontWeight.BOLD,
                            color=THEME.text_primary,
                            expand=True
                        ),
                        ft.Text(f"{len(changes)} 个变更", size=11, color=THEME.text_muted),
                    ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)

                    group_changes_col = ft.Column(spacing=4)
                    for original_index, change in changes:
                        old_text = format_stage_value(change["old_value"])
                        new_text = format_stage_value(change["new_value"])
                        group_changes_col.controls.append(ft.Container(
                            content=ft.Row([
                                ft.Text(
                                    f"#{original_index + 1}",
                                    size=12,
                                    color=THEME.mc_gold,
                                    width=34
                                ),
                                ft.Column([
                                    ft.Text(
                                        change["display_path"],
                                        size=12,
                                        color=THEME.text_primary
                                    ),
                                    ft.Text(
                                        f"{old_text} → {new_text}",
                                        size=11,
                                        color=THEME.text_muted
                                    ),
                                ], spacing=2, expand=True),
                                ft.TextButton(
                                    "撤销",
                                    on_click=lambda e, i=original_index: self.unstage_change(i)
                                ),
                            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                            padding=ft.Padding(left=6, right=6, top=4, bottom=4),
                            bgcolor=THEME.bg_secondary,
                            border_radius=4,
                        ))

                    self.ctx._nbt_stage_list.controls.append(ft.Container(
                        content=ft.Column([
                            group_header,
                            group_changes_col,
                        ], spacing=6),
                        padding=ft.Padding(left=8, right=8, top=8, bottom=8),
                        bgcolor=THEME.bg_card,
                        border_radius=6,
                    ))
            safe_update(self.ctx._nbt_stage_list)
        except Exception as ex:
            self.ctx.app.handle_exception(ex, title="渲染暂存区列表失败")

    # ==================== 查询方法 ====================

    def get_staged_count(self) -> int:
        """获取暂存的变更数量"""
        return len(self.ctx._staged_nbt_changes)

    def has_changes(self) -> bool:
        """是否有暂存的变更"""
        return bool(self.ctx._staged_nbt_changes)

    def get_changes_by_target(self) -> Dict[str, List[Dict]]:
        """按目标文件分组获取变更"""
        grouped: Dict[str, List[Dict]] = {}
        for change in self.ctx._staged_nbt_changes:
            target_key = str(change["target"])
            if target_key not in grouped:
                grouped[target_key] = []
            grouped[target_key].append(change)
        return grouped
