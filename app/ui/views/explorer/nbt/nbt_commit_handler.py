"""NBT Commit Handler - 负责提交 NBT 变更到存档"""
from typing import Any, Dict, List

import flet as ft

from app.ui.theme import THEME
from app.ui.views.explorer.explorer_helpers import format_change_summary
from core.omni.world_session import WorldSession


class NbtCommitHandler:
    """NBT 提交处理器 - 管理变更的提交流程"""

    def __init__(self, context: Any):
        """
        Args:
            context: 上下文对象，需要提供 world_session, _staged_nbt_changes 等
        """
        self.ctx = context

    # ==================== 提交入口 ====================

    def commit_changes(self, e: Any = None) -> None:
        """提交暂存的 NBT 变更"""
        try:
            if not self.ctx.world_session:
                self.ctx.app.warn_dialog("提示", "请先通过侧边栏设置当前存档。")
                return
            if not self.ctx._staged_nbt_changes:
                self.ctx.app.info_dialog("提示", "暂存区没有可提交的变更。")
                return
            self.show_commit_preview_dialog()
        except Exception as ex:
            self.ctx.app.handle_exception(ex, title="提交 NBT 变更失败")

    # ==================== 预览对话框 ====================

    def show_commit_preview_dialog(self) -> None:
        """显示提交预览对话框"""
        if not self.ctx.page:
            self.execute_commit()
            return

        summary_controls: List[ft.Control] = []
        for index, change in enumerate(self.ctx._staged_nbt_changes[:80]):
            summary_controls.append(ft.Container(
                content=ft.Text(
                    format_change_summary(index, change),
                    size=12,
                    color=THEME.text_secondary,
                    font_family="Consolas",
                ),
                padding=ft.Padding(left=8, right=8, top=6, bottom=6),
                bgcolor=THEME.bg_card,
            ))

        if len(self.ctx._staged_nbt_changes) > 80:
            summary_controls.append(ft.Text(
                f"还有 {len(self.ctx._staged_nbt_changes) - 80} 个变更未展示，提交时会一并写入。",
                size=12,
                color=THEME.warning,
            ))

        dialog = ft.AlertDialog(
            title=ft.Text("提交变更预览", color=THEME.text_primary),
            content=ft.Column([
                ft.Text(
                    f"即将提交 {len(self.ctx._staged_nbt_changes)} 个变更。提交前会自动备份当前存档。",
                    size=13,
                    color=THEME.text_primary,
                ),
                ft.Column(summary_controls, spacing=6, scroll=ft.ScrollMode.AUTO, height=360),
            ], tight=True, spacing=10),
            actions=[],
        )

        def close_dialog(e: Any = None) -> None:
            dialog.open = False
            self.ctx.page.update()

        def confirm_commit(e: Any = None) -> None:
            dialog.open = False
            self.ctx.page.update()
            self.execute_commit()

        dialog.actions = [
            ft.TextButton("确认提交", on_click=confirm_commit),
            ft.TextButton("取消", on_click=close_dialog),
        ]
        self.ctx.page.overlay.append(dialog)
        dialog.open = True
        self.ctx.page.update()

    # ==================== 执行提交 ====================

    def execute_commit(self) -> None:
        """执行 NBT 变更提交"""
        try:
            if not self.ctx.world_session:
                self.ctx.app.warn_dialog("提示", "请先通过侧边栏设置当前存档。")
                return
            if not self.ctx._staged_nbt_changes:
                self.ctx.app.info_dialog("提示", "暂存区没有可提交的变更。")
                return

            # 处理区块变更：将同一区块的所有变更合并为完整区块数据队列
            chunk_changes: Dict[tuple, Dict] = {}
            normal_changes: List[Dict] = []

            for change in self.ctx._staged_nbt_changes:
                if change.get("format") == "chunk":
                    target = change["target"]
                    if isinstance(target, dict) and "region_path" in target:
                        key = (str(target["region_path"]), target["chunk_x"], target["chunk_z"])
                        if key not in chunk_changes:
                            chunk_changes[key] = {
                                "target": target,
                                "latest_data": target["data"]
                            }
                else:
                    normal_changes.append(change)

            # 队列化普通变更
            for change in normal_changes:
                if change.get("format") == "json":
                    self.ctx.world_session.queue_modify_json(
                        change["target"],
                        change["path"],
                        change["new_value"],
                        operation=change.get("operation", "set"),
                    )
                else:
                    self.ctx.world_session.queue_modify_nbt(
                        change["target"],
                        change["path"],
                        change["new_value"],
                        operation=change.get("operation", "set"),
                    )

            # 队列化区块变更
            for (region_path_str, cx, cz), chunk_info in chunk_changes.items():
                target = chunk_info["target"]
                region_path = target["region_path"]
                full_data = chunk_info["latest_data"]
                self.ctx.world_session.queue_modify_chunk(
                    region_path,
                    cx,
                    cz,
                    full_data
                )

            queued = self.ctx.world_session.get_queue_size()
            success = self.ctx.world_session.commit(backup=True)

            if success:
                committed = len(self.ctx._staged_nbt_changes)
                self.ctx._staged_nbt_changes.clear()

                # 更新暂存区状态
                if hasattr(self.ctx, '_stage_manager'):
                    self.ctx._stage_manager.update_stage_status()

                # 重新加载 WorldSession
                self.ctx.world_session = WorldSession(
                    self.ctx.world_session.world_path,
                    log=self.ctx.app.log
                )

                # 重新加载当前 NBT 目标
                if hasattr(self.ctx, '_data_loader'):
                    self.ctx._data_loader.reload_current_nbt_target()

                self.ctx.app.info_dialog(
                    "提交完成",
                    f"已提交 {committed} 个 NBT/JSON/区块变更。提交前已创建备份。"
                )
            else:
                self.ctx.app.error_dialog(
                    "提交失败",
                    f"已排队 {queued} 个操作，但提交失败。请查看日志。"
                )
        except Exception as ex:
            self.ctx.app.handle_exception(ex, title="提交 NBT 变更失败")

    # ==================== 辅助方法 ====================

    def get_commit_summary(self) -> str:
        """获取提交摘要"""
        if not self.ctx._staged_nbt_changes:
            return "无变更"

        # 统计变更类型
        by_format: Dict[str, int] = {}
        for change in self.ctx._staged_nbt_changes:
            fmt = change.get("format", "unknown")
            by_format[fmt] = by_format.get(fmt, 0) + 1

        parts = []
        if "nbt" in by_format:
            parts.append(f"{by_format['nbt']} 个 NBT")
        if "json" in by_format:
            parts.append(f"{by_format['json']} 个 JSON")
        if "chunk" in by_format:
            parts.append(f"{by_format['chunk']} 个区块")

        return f"共 {len(self.ctx._staged_nbt_changes)} 个变更：" + "、".join(parts)
