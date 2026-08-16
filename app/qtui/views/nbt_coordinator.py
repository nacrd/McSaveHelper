"""Qt NBT 面板、暂存状态与安全提交的协调器。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

from app.models.nbt_edit import ChunkNbtTarget, NbtChange, NbtPath, NbtStageStore
from app.qtui.context import (
    QtDialogPort,
    QtProgressPort,
    QtRuntimePort,
    QtTranslationPort,
)
from app.qtui.views.nbt import QtNbtPanel
from app.qtui.views.nbt_tasks import (
    NbtCommitCompletion,
    NbtTaskCallbacks,
    NbtTasks,
)
from app.services.nbt_chunk_service import (
    ChunkLoadResult,
    ChunkMissingError,
    ChunkPathError,
    region_file_relative,
    world_coords_to_region_chunk,
)
from app.services.nbt_document_service import (
    LoadedNbtDocument,
    NbtDocumentTarget,
)
from core.mca.map_models import BLOCKS_PER_REGION
from core.omni.world_session import WorldSession


class QtNbtHost(
    QtTranslationPort,
    QtDialogPort,
    QtProgressPort,
    QtRuntimePort,
    Protocol,
):
    """NBT 工作流所需的应用端口。"""


class QtNbtCoordinator:
    """连接 Qt NBT 面板、暂存快照和共享事务服务。"""

    def __init__(
        self,
        app: QtNbtHost,
        reload_world: Callable[[Path], None],
    ) -> None:
        """创建 NBT 协调器。

        Args:
            app: NBT 工作流所需的 UI 与运行时端口。
            reload_world: 提交成功后重建世界读会话的回调。
        """
        self._app = app
        self._reload_world = reload_world
        self._store = NbtStageStore()
        self._session: WorldSession | None = None
        self._document: LoadedNbtDocument | None = None
        self._chunk_target: ChunkNbtTarget | None = None
        self._chunk_label = ""
        self._dimension_id = "overworld"
        self._suppress_autoload = False
        self.panel = QtNbtPanel(
            app.translate,
            self.load_selected,
            self.reload_document,
            self.stage_change,
            self.remove_selected,
            self.discard_all,
            self.commit_all,
            self.load_chunk,
            self.fill_from_world_coords,
        )
        self._tasks = NbtTasks(
            app.execution_runtime,
            NbtTaskCallbacks(
                targets_ready=self._targets_ready,
                targets_error=self._targets_error,
                document_ready=self._document_ready,
                document_error=self._document_error,
                chunk_ready=self._chunk_ready,
                chunk_error=self._chunk_error,
                commit_success=self._commit_success,
                commit_error=self._commit_error,
                commit_cancelled=self._commit_cancelled,
                commit_finished=self._commit_finished,
            ),
        )

    @property
    def staged_changes(self) -> tuple[NbtChange, ...]:
        """返回当前世界的不可变暂存快照。"""
        return self._store.changes

    @property
    def chunk_target(self) -> ChunkNbtTarget | None:
        """返回当前已加载的区块目标。"""
        return self._chunk_target

    def set_world(
        self,
        session: WorldSession,
        *,
        dimension_id: str = "overworld",
    ) -> None:
        """绑定新世界、丢弃旧世界暂存项并开始扫描目标。"""
        self._session = session
        self._document = None
        self._chunk_target = None
        self._chunk_label = ""
        self._dimension_id = dimension_id or "overworld"
        self._suppress_autoload = False
        self._store.clear()
        self.panel.show_world(True)
        self.panel.show_stages(())
        try:
            self._tasks.set_world(session)
        except (RuntimeError, ValueError) as error:
            self._targets_error(error, self._tasks.world_generation)

    def clear_world(self) -> None:
        """取消 NBT 操作并清除世界、文档和暂存身份。"""
        was_committing = self._tasks.is_committing
        self._tasks.clear_world()
        self._session = None
        self._document = None
        self._chunk_target = None
        self._chunk_label = ""
        self._store.clear()
        self.panel.show_world(False)
        if was_committing:
            self._app.hide_progress()

    def set_dimension(self, dimension_id: str) -> None:
        """更新当前维度，供世界坐标填入区域路径使用。"""
        if dimension_id:
            self._dimension_id = dimension_id

    def load_selected(self) -> None:
        """读取目标下拉框中选中的 NBT/JSON 文档。"""
        target = self.panel.selected_target
        if self._session is None or target is None:
            return
        self._suppress_autoload = False
        self._chunk_target = None
        self._chunk_label = ""
        try:
            if self._tasks.load_document(target):
                self.panel.show_loading()
        except (RuntimeError, ValueError) as error:
            self._document_error(
                error,
                self._tasks.world_generation,
                0,
            )

    def reload_document(self) -> None:
        """从磁盘重载当前目标，并重新叠加仍在暂存区的值。"""
        if self._chunk_target is not None:
            self.load_chunk()
            return
        self.load_selected()

    def load_chunk(self) -> None:
        """按表单中的区域路径与区块坐标异步加载区块 NBT。"""
        if self._session is None:
            self._warn("nbt_editor.no_world", "未加载存档")
            return
        relative_text = self.panel.region_file_text
        if not relative_text:
            self._app.warn_dialog(
                self._t("dialogs.hint", "提示"),
                self._t(
                    "nbt_editor.need_region",
                    "请输入区域文件路径，例如 region/r.0.0.mca。",
                ),
            )
            return
        try:
            chunk_x, chunk_z = self.panel.chunk_coords
        except ValueError:
            self._app.warn_dialog(
                self._t("dialogs.hint", "提示"),
                self._t("nbt_editor.chunk_int", "区块坐标必须是整数。"),
            )
            return
        self._suppress_autoload = True
        try:
            if self._tasks.load_chunk(
                Path(relative_text),
                relative_text,
                chunk_x,
                chunk_z,
            ):
                self._document = None
                self.panel.show_loading()
        except (RuntimeError, ValueError) as error:
            self._chunk_error(error, self._tasks.world_generation, 0)

    def fill_from_world_coords(self) -> None:
        """根据世界坐标填入区域路径与区块局部坐标。"""
        try:
            world_x, world_z = self.panel.world_coords
        except ValueError:
            self._app.warn_dialog(
                self._t("dialogs.hint", "提示"),
                self._t("nbt_editor.world_number", "世界坐标必须是数字。"),
            )
            return
        region_x, region_z, chunk_x, chunk_z = world_coords_to_region_chunk(
            int(world_x),
            int(world_z),
        )
        self.panel.set_chunk_fields(
            region_file_relative(self._dimension_id, region_x, region_z),
            chunk_x,
            chunk_z,
            world_x=int(world_x),
            world_z=int(world_z),
        )

    def open_region_chunk(
        self,
        region_x: int,
        region_z: int,
        *,
        dimension_id: str | None = None,
        local_chunk_x: int = 0,
        local_chunk_z: int = 0,
    ) -> None:
        """从地图选区打开指定区域的区块 NBT。"""
        if dimension_id:
            self._dimension_id = dimension_id
        relative = region_file_relative(
            self._dimension_id, region_x, region_z
        )
        block_x = region_x * BLOCKS_PER_REGION + local_chunk_x * 16
        block_z = region_z * BLOCKS_PER_REGION + local_chunk_z * 16
        self.panel.set_chunk_fields(
            relative,
            local_chunk_x,
            local_chunk_z,
            world_x=block_x,
            world_z=block_z,
        )
        self.load_chunk()

    def stage_change(
        self,
        path: NbtPath,
        old_value: object,
        new_value: object,
        display_path: str,
    ) -> None:
        """把树编辑转换为不可变变更并刷新审阅区。"""
        if self._tasks.is_committing:
            return
        if self._chunk_target is not None:
            change = NbtChange.create(
                target=self._chunk_target,
                target_label=self._chunk_label or self._chunk_target.key,
                format="chunk",
                path=path,
                display_path=display_path,
                old_value=old_value,
                new_value=new_value,
            )
        else:
            document = self._document
            if document is None:
                return
            change = NbtChange.create(
                target=document.target.relative_path,
                target_label=document.target.label,
                format=document.target.format,
                path=path,
                display_path=display_path,
                old_value=old_value,
                new_value=new_value,
            )
        self._store.add(change)
        self.panel.show_stages(self._store.changes)
        self._app.log(f"已暂存 NBT 修改: {display_path}", "QUEUE")

    def stage_external_changes(
        self,
        changes: Sequence[NbtChange],
    ) -> int:
        """把玩家表单等外部来源的变更并入共享暂存区。

        Args:
            changes: 已校验的不可变变更序列。

        Returns:
            实际写入暂存区的变更数量。
        """
        if self._tasks.is_committing or not changes:
            return 0
        for change in changes:
            self._store.add(change)
        self.panel.show_stages(self._store.changes)
        self._app.log(
            f"已暂存外部 NBT 修改: {len(changes)} 个",
            "QUEUE",
        )
        return len(changes)

    def remove_selected(self) -> None:
        """撤销暂存表选中的单条变更。"""
        index = self.panel.selected_stage_index
        if index is None or self._store.remove(index) is None:
            return
        self.panel.show_stages(self._store.changes)
        self.reload_document()

    def discard_all(self) -> None:
        """确认后丢弃当前世界的全部暂存变更。"""
        count = len(self._store)
        if not count or not self.panel.confirm_discard(count):
            return
        self._store.clear()
        self.panel.show_stages(())
        self.reload_document()
        self._app.info_dialog(
            self._t("nbt_editor.discarded_title", "已丢弃"),
            self._t("nbt_editor.discarded_message", "暂存变更已全部丢弃。"),
        )

    def commit_all(self) -> None:
        """确认预览后异步提交当前暂存快照。"""
        changes = self._store.changes
        if self._session is None:
            self._warn("nbt_editor.no_world", "未加载存档")
            return
        if not changes:
            self._warn("nbt_editor.no_changes", "暂存区没有可提交的变更")
            return
        if self._tasks.is_committing:
            self._warn("nbt_commit.busy_message", "已有 NBT 提交正在执行")
            return
        if not self.panel.confirm_commit(changes):
            return
        try:
            if not self._tasks.submit_commit(changes):
                return
        except (RuntimeError, ValueError) as error:
            self._commit_error(error, self._tasks.world_generation)
            return
        self.panel.set_busy(True)
        self._app.show_progress(self._t(
            "nbt_editor.committing", "正在备份并提交 NBT 变更..."
        ))

    def _targets_ready(
        self,
        targets: tuple[NbtDocumentTarget, ...],
        generation: int,
    ) -> None:
        del generation
        self.panel.show_targets(targets)
        # 若用户已请求区块 NBT，不要用 level.dat 自动加载冲掉该请求。
        if targets and not self._suppress_autoload:
            self.load_selected()

    def _targets_error(self, error: Exception, generation: int) -> None:
        del generation
        self.panel.show_load_error(error)
        self._app.handle_exception(error, title=self._t(
            "nbt_editor.scan_failed", "扫描 NBT 文档失败"
        ))

    def _document_ready(
        self,
        document: LoadedNbtDocument,
        world_generation: int,
        document_generation: int,
    ) -> None:
        del world_generation, document_generation
        self._document = document
        self._chunk_target = None
        self._chunk_label = ""
        self.panel.show_document(document, self._store.changes)

    def _document_error(
        self,
        error: Exception,
        world_generation: int,
        document_generation: int,
    ) -> None:
        del world_generation, document_generation
        self._document = None
        self.panel.show_load_error(error)
        self._app.handle_exception(error, title=self._t(
            "nbt_editor.load_error_title", "读取 NBT 文档失败"
        ))

    def _chunk_ready(
        self,
        result: ChunkLoadResult,
        world_generation: int,
        document_generation: int,
    ) -> None:
        del world_generation, document_generation
        target = ChunkNbtTarget(
            region_path=result.region_path,
            chunk_x=result.chunk_x,
            chunk_z=result.chunk_z,
            data=result.data,
        )
        label = (
            f"区块 NBT: {result.relative_text} "
            f"[{result.chunk_x}, {result.chunk_z}]"
        )
        self._chunk_target = target
        self._chunk_label = label
        self._document = None
        self.panel.show_chunk(target, label, self._store.changes)

    def _chunk_error(
        self,
        error: Exception,
        world_generation: int,
        document_generation: int,
    ) -> None:
        del world_generation, document_generation
        self._chunk_target = None
        self._chunk_label = ""
        self.panel.show_load_error(error)
        if isinstance(error, (ChunkMissingError, ChunkPathError, ValueError)):
            self._app.warn_dialog(
                self._t("dialogs.hint", "提示"),
                str(error),
            )
            return
        self._app.handle_exception(error, title=self._t(
            "nbt_editor.chunk_load_failed", "加载区块 NBT 失败"
        ))

    def _commit_success(
        self,
        completion: NbtCommitCompletion,
        generation: int,
    ) -> None:
        del generation
        result = completion.result
        if not result.committed:
            self._app.error_dialog(
                self._t("nbt_editor.commit_failed", "提交失败"),
                self._t(
                    "nbt_editor.commit_rejected",
                    "已排队 {count} 个操作，但事务未提交。",
                    count=result.queued_operations,
                ),
            )
            return
        self._store.remove_snapshot(completion.changes)
        self.panel.show_stages(self._store.changes)
        self._app.info_dialog(
            self._t("nbt_editor.commit_done", "提交完成"),
            self._t(
                "nbt_editor.commit_done_message",
                "已提交 {count} 个变更，提交前已创建备份。",
                count=result.requested_changes,
            ),
        )
        try:
            self._reload_world(result.world_path)
        except (OSError, RuntimeError, ValueError) as error:
            self._app.log(f"NBT 提交成功，但重载世界失败: {error}", "WARNING")

    def _commit_error(self, error: Exception, generation: int) -> None:
        del generation
        self._app.handle_exception(error, title=self._t(
            "nbt_editor.commit_failed", "提交失败"
        ))

    def _commit_cancelled(self, generation: int) -> None:
        del generation
        self._app.warn_dialog(
            self._t("nbt_commit.cancelled_title", "提交已取消"),
            self._t(
                "nbt_commit.cancelled_message",
                "NBT 提交已在安全检查点取消，原存档保持不变。",
            ),
        )

    def _commit_finished(self, generation: int) -> None:
        del generation
        self.panel.set_busy(False)
        self._app.hide_progress()

    def _warn(self, key: str, default: str) -> None:
        self._app.warn_dialog(
            self._t("common.tip", "提示"),
            self._t(key, default),
        )

    def _t(self, key: str, default: str = "", **kwargs: Any) -> str:
        return self._app.translate(key, default, **kwargs)

    def close(self) -> None:
        """幂等关闭 NBT 后台任务。"""
        was_committing = self._tasks.is_committing
        self._tasks.close()
        self._session = None
        self._document = None
        self._chunk_target = None
        if was_committing:
            self._app.hide_progress()


__all__ = ["QtNbtCoordinator", "QtNbtHost"]
