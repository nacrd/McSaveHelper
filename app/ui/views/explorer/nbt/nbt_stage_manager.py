"""NBT 暂存区的交互与渲染。"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

import flet as ft

from app.models.nbt_edit import (
    NbtChange,
    NbtEditFormat,
    NbtPathPart,
    NbtStageStore,
    NbtTarget,
)
from app.ui.components.cards import placeholder
from app.ui.icons import IconSet
from app.ui.theme import THEME
from app.ui.views.explorer.explorer_helpers import format_stage_value
from app.ui.views.explorer.utils import safe_update


DialogCallback = Callable[[str, str], None]
ErrorCallback = Callable[[Exception, str], None]
LogCallback = Callable[[str, str], None]


class NbtStageManager:
    """协调纯暂存状态与 Flet 暂存区控件。

    不负责写盘；提交由上层事务服务读取 ``get_changes_by_target``。
    """

    def __init__(
        self,
        *,
        store: NbtStageStore,
        status_control: ft.Text,
        list_control: ft.Column,
        get_current_target: Callable[[], Optional[NbtTarget]],
        get_current_label: Callable[[], str],
        get_current_format: Callable[[], NbtEditFormat],
        reload_current_target: Callable[[], None],
        warn: DialogCallback,
        info: DialogCallback,
        handle_error: ErrorCallback,
        log: LogCallback,
    ) -> None:
        """绑定暂存存储与 UI 控件回调。

        Args:
            store: 纯状态暂存区。
            status_control: 显示「暂存区: N 个变更」的文本。
            list_control: 变更列表容器。
            get_current_target: 取当前编辑目标；未加载返回 None。
            get_current_label: 当前目标展示标签。
            get_current_format: 当前编辑格式（player/chunk 等）。
            reload_current_target: 撤销后重载当前 NBT 视图。
            warn: 警告对话框 ``(title, message)``。
            info: 信息对话框 ``(title, message)``。
            handle_error: 异常处理 ``(exc, context)``。
            log: 操作日志 ``(message, category)``。
        """
        self._store = store
        self._status_control = status_control
        self._list_control = list_control
        self._get_current_target = get_current_target
        self._get_current_label = get_current_label
        self._get_current_format = get_current_format
        self._reload_current_target = reload_current_target
        self._warn = warn
        self._info = info
        self._handle_error = handle_error
        self._log = log

    def stage_change(
        self,
        path_parts: List[NbtPathPart],
        old_value: Any,
        new_value: Any,
        display_path: str,
    ) -> None:
        """暂存一个 NBT 修改到当前目标。

        Args:
            path_parts: 从根到字段的路径片段。
            old_value: 修改前的值。
            new_value: 修改后的值。
            display_path: UI 展示用路径字符串。
        """
        try:
            target = self._get_current_target()
            if target is None:
                self._warn("提示", "请先加载要编辑的 NBT 数据。")
                return

            self._store.add(NbtChange.create(
                target=target,
                target_label=self._get_current_label(),
                format=self._get_current_format(),
                path=path_parts,
                display_path=display_path,
                old_value=old_value,
                new_value=new_value,
            ))
            self.update_stage_status()
            self._log(f"已暂存 NBT 修改: {display_path}", "QUEUE")
        except Exception as ex:
            self._handle_error(ex, "暂存 NBT 修改失败")

    def unstage_change(self, index: int) -> None:
        """按全局序号撤销一条暂存变更并重载当前目标。

        Args:
            index: 暂存列表中的 0-based 序号。
        """
        try:
            if self._store.remove(index) is None:
                return
            self.update_stage_status()
            self._reload_current_target()
        except Exception as ex:
            self._handle_error(ex, "撤销暂存变更失败")

    def discard_all_changes(self, e: Any = None) -> None:
        """丢弃所有暂存的变更。"""
        try:
            if not self._store:
                self._info("提示", "暂存区没有变更。")
                return
            self._store.clear()
            self.update_stage_status()
            self._reload_current_target()
            self._info(
                "已丢弃",
                "已丢弃暂存区中的 NBT 变更，并重新加载当前 NBT 数据。",
            )
        except Exception as ex:
            self._handle_error(ex, "丢弃 NBT 变更失败")

    def update_stage_status(self) -> None:
        """更新暂存区状态显示。"""
        try:
            count = len(self._store)
            self._status_control.value = f"暂存区: {count} 个变更"
            self._status_control.color = (
                THEME.warning if count else THEME.text_muted
            )
            self.render_stage_list()
            safe_update(self._status_control)
        except Exception as ex:
            self._handle_error(ex, "更新暂存区状态失败")

    def render_stage_list(self) -> None:
        """渲染按目标分组的暂存变更。"""
        try:
            self._list_control.controls.clear()
            if not self._store:
                self._list_control.controls.append(placeholder(
                    icon=IconSet.CLIPBOARD,
                    title="暂无暂存变更",
                    subtitle="对 NBT 树中的字段进行编辑后，变更会暂存在此处等待提交",
                    height=120,
                ))
            else:
                for changes in self._store.grouped_by_target().values():
                    first_change = changes[0][1]
                    group_header = ft.Row(
                        [
                            ft.Icon(
                                IconSet.FOLDER_OPEN,
                                size=16,
                                color=THEME.accent,
                            ),
                            ft.Text(
                                first_change.target_label,
                                size=13,
                                weight=ft.FontWeight.BOLD,
                                color=THEME.text_primary,
                                expand=True,
                            ),
                            ft.Text(
                                f"{len(changes)} 个变更",
                                size=11,
                                color=THEME.text_muted,
                            ),
                        ],
                        spacing=6,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    )
                    group_changes = ft.Column(spacing=4)
                    for original_index, change in changes:
                        group_changes.controls.append(
                            self._build_change_row(original_index, change)
                        )
                    self._list_control.controls.append(ft.Container(
                        content=ft.Column(
                            [group_header, group_changes],
                            spacing=6,
                        ),
                        padding=ft.Padding(left=8, right=8, top=8, bottom=8),
                        bgcolor=THEME.bg_card,
                        border_radius=6,
                    ))
            safe_update(self._list_control)
        except Exception as ex:
            self._handle_error(ex, "渲染暂存区列表失败")

    def _build_change_row(
        self,
        original_index: int,
        change: NbtChange,
    ) -> ft.Container:
        old_text = format_stage_value(change.old_value)
        new_text = format_stage_value(change.new_value)
        return ft.Container(
            content=ft.Row(
                [
                    ft.Text(
                        f"#{original_index + 1}",
                        size=12,
                        color=THEME.mc_gold,
                        width=34,
                    ),
                    ft.Column(
                        [
                            ft.Text(
                                change.display_path,
                                size=12,
                                color=THEME.text_primary,
                            ),
                            ft.Text(
                                f"{old_text} → {new_text}",
                                size=11,
                                color=THEME.text_muted,
                            ),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                    ft.TextButton(
                        "撤销",
                        on_click=lambda e, i=original_index: self.unstage_change(i),
                    ),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding(left=6, right=6, top=4, bottom=4),
            bgcolor=THEME.bg_secondary,
            border_radius=4,
        )

    def get_staged_count(self) -> int:
        """返回当前暂存变更条数。

        Returns:
            暂存区长度。
        """
        return len(self._store)

    def has_changes(self) -> bool:
        """是否存在待提交变更。

        Returns:
            暂存区非空时为 True。
        """
        return bool(self._store)

    def get_changes_by_target(self) -> Dict[str, List[NbtChange]]:
        """按目标键分组返回暂存变更（去掉内部序号）。

        Returns:
            目标键 → ``NbtChange`` 列表。
        """
        return {
            key: [change for _, change in changes]
            for key, changes in self._store.grouped_by_target().items()
        }
