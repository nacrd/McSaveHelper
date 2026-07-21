"""将类型化的 NBT 暂存变更提交到存档。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import flet as ft

from app.models.nbt_edit import ChunkNbtTarget, NbtChange, NbtStageStore
from app.ui.theme import THEME
from app.ui.views.explorer.explorer_helpers import format_change_summary
from core.omni.world_session import WorldSession
from core.types import LogCallback


DialogCallback = Callable[[str, str], None]
ErrorCallback = Callable[[Exception, str], None]
SessionFactory = Callable[[Path, LogCallback], WorldSession]


class NbtCommitHandler:
    """负责提交预览、队列转换与会话刷新。"""

    def __init__(
        self,
        *,
        store: NbtStageStore,
        get_world_session: Callable[[], Optional[WorldSession]],
        replace_world_session: Callable[[WorldSession], None],
        get_page: Callable[[], Optional[ft.Page]],
        refresh_stage: Callable[[], None],
        reload_current_target: Callable[[], None],
        warn: DialogCallback,
        info: DialogCallback,
        error: DialogCallback,
        handle_error: ErrorCallback,
        log: LogCallback,
        session_factory: Optional[SessionFactory] = None,
    ) -> None:
        """注入提交所需的会话与 UI 端口。"""
        self._store = store
        self._get_world_session = get_world_session
        self._replace_world_session = replace_world_session
        self._get_page = get_page
        self._refresh_stage = refresh_stage
        self._reload_current_target = reload_current_target
        self._warn = warn
        self._info = info
        self._error = error
        self._handle_error = handle_error
        self._log = log
        self._session_factory = session_factory

    def commit_changes(self, e: object = None) -> None:
        """验证当前状态并打开提交预览。"""
        try:
            if not self._get_world_session():
                self._warn("提示", "请先通过侧边栏设置当前存档。")
                return
            if not self._store:
                self._info("提示", "暂存区没有可提交的变更。")
                return
            self.show_commit_preview_dialog()
        except Exception as ex:
            self._handle_error(ex, "提交 NBT 变更失败")

    def show_commit_preview_dialog(self) -> None:
        """显示提交预览；无页面环境时直接提交。"""
        page = self._get_page()
        if not page:
            self.execute_commit()
            return

        changes = self._store.changes
        dialog = ft.AlertDialog(
            title=ft.Text("提交变更预览", color=THEME.text_primary),
            content=self._build_commit_preview_content(changes),
            actions=[],
        )

        def close_dialog(e: object = None) -> None:
            dialog.open = False
            page.update()

        def confirm_commit(e: object = None) -> None:
            dialog.open = False
            page.update()
            self.execute_commit()

        dialog.actions = [
            ft.TextButton("确认提交", on_click=confirm_commit),
            ft.TextButton("取消", on_click=close_dialog),
        ]
        page.overlay.append(dialog)
        dialog.open = True
        page.update()

    def _build_commit_preview_content(
        self,
        changes: Sequence[NbtChange],
    ) -> ft.Column:
        summary_controls: List[ft.Control] = []
        for index, change in enumerate(changes[:80]):
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
        if len(changes) > 80:
            summary_controls.append(ft.Text(
                f"还有 {len(changes) - 80} 个变更未展示，提交时会一并写入。",
                size=12,
                color=THEME.warning,
            ))
        return ft.Column(
            [
                ft.Text(
                    f"即将提交 {len(changes)} 个变更。提交前会自动备份当前存档。",
                    size=13,
                    color=THEME.text_primary,
                ),
                ft.Column(
                    summary_controls,
                    spacing=6,
                    scroll=ft.ScrollMode.AUTO,
                    height=360,
                ),
            ],
            tight=True,
            spacing=10,
        )

    def execute_commit(self) -> None:
        """将暂存变更转换为 WorldSession 队列并原子提交。"""
        try:
            session = self._get_world_session()
            if not session:
                self._warn("提示", "请先通过侧边栏设置当前存档。")
                return
            if not self._store:
                self._info("提示", "暂存区没有可提交的变更。")
                return

            changes = self._store.changes
            chunk_changes, normal_changes = self._partition_changes(changes)
            self._queue_normal_changes(session, normal_changes)
            for target, target_changes in chunk_changes.values():
                loaded = session.load_chunk_nbt(
                    target.region_path,
                    target.chunk_x,
                    target.chunk_z,
                )
                if loaded is None:
                    raise ValueError(f"无法重新加载待提交区块: {target.key}")
                chunk_data = loaded[0]
                for change in target_changes:
                    self._apply_change(chunk_data, change)
                session.queue_modify_chunk(
                    target.region_path,
                    target.chunk_x,
                    target.chunk_z,
                    chunk_data,
                )

            queued = session.get_queue_size()
            if not session.commit(backup=True):
                self._error(
                    "提交失败",
                    f"已排队 {queued} 个操作，但提交失败。请查看日志。",
                )
                return

            committed = self._store.clear()
            self._refresh_stage()
            new_session = (
                self._session_factory(session.world_path, self._log)
                if self._session_factory
                else session.spawn()
            )
            self._replace_world_session(new_session)
            self._reload_current_target()
            self._info(
                "提交完成",
                f"已提交 {committed} 个 NBT/JSON/区块变更。提交前已创建备份。",
            )
        except Exception as ex:
            self._handle_error(ex, "提交 NBT 变更失败")

    @staticmethod
    def _partition_changes(
        changes: Tuple[NbtChange, ...],
    ) -> Tuple[Dict[str, Tuple[ChunkNbtTarget, List[NbtChange]]], List[NbtChange]]:
        chunk_changes: Dict[str, Tuple[ChunkNbtTarget, List[NbtChange]]] = {}
        normal_changes: List[NbtChange] = []
        for change in changes:
            if isinstance(change.target, ChunkNbtTarget):
                entry = chunk_changes.setdefault(
                    change.target.key,
                    (change.target, []),
                )
                entry[1].append(change)
            else:
                normal_changes.append(change)
        return chunk_changes, normal_changes

    @staticmethod
    def _apply_change(data: Any, change: NbtChange) -> None:
        if not change.path:
            raise ValueError("区块变更路径不能为空")
        node = data
        for part in change.path[:-1]:
            node = node[part]
        key = change.path[-1]
        if change.operation == "delete":
            del node[key]
        elif change.operation == "add" and isinstance(key, int):
            node.insert(key, change.new_value)
        else:
            node[key] = change.new_value

    @staticmethod
    def _queue_normal_changes(
        session: WorldSession,
        changes: List[NbtChange],
    ) -> None:
        for change in changes:
            target = change.target
            if isinstance(target, ChunkNbtTarget):
                raise ValueError("区块变更不能进入普通 NBT/JSON 提交队列")
            path = list(change.path)
            if change.format == "json":
                session.queue_modify_json(
                    target,
                    path,
                    change.new_value,
                    operation=change.operation,
                )
            else:
                session.queue_modify_nbt(
                    target,
                    path,
                    change.new_value,
                    operation=change.operation,
                )

    def get_commit_summary(self) -> str:
        """生成待提交变更的摘要文本。"""
        if not self._store:
            return "无变更"

        counts = self._store.count_by_format()
        parts = []
        if "nbt" in counts:
            parts.append(f"{counts['nbt']} 个 NBT")
        if "json" in counts:
            parts.append(f"{counts['json']} 个 JSON")
        if "chunk" in counts:
            parts.append(f"{counts['chunk']} 个区块")
        return f"共 {len(self._store)} 个变更：" + "、".join(parts)
