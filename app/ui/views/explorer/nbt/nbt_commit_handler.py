"""将类型化的 NBT 暂存变更提交到存档。"""
from __future__ import annotations

from concurrent.futures import CancelledError
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

import flet as ft

from app.models.nbt_edit import NbtChange, NbtStageStore
from app.services.execution_runtime import (
    OperationCancelledError,
    OperationHandle,
    OperationScope,
    RuntimeClosedError,
    TaskPriority,
    TaskQueueFullError,
)
from app.services.nbt_commit_service import (
    NbtCommitResult,
    commit_nbt_changes,
)
from app.ui.theme import THEME
from app.ui.views.explorer.explorer_helpers import format_change_summary
from core.omni.world_session import WorldSession
from core.types import LogCallback


DialogCallback = Callable[[str, str], None]
ErrorCallback = Callable[[Exception, str], None]
ReloadWorld = Callable[[Path], None]
WorldIdentityCheck = Callable[[Path], bool]
UiDispatch = Callable[[Callable[[], None]], None]


@dataclass(frozen=True)
class NbtCommitExecution:
    """后台运行、视图身份与成功刷新端口。"""

    scope: OperationScope
    post_to_ui: UiDispatch
    get_generation: Callable[[], int]
    is_world_current: WorldIdentityCheck
    reload_world: ReloadWorld


@dataclass(frozen=True)
class NbtCommitUi:
    """提交协调器使用的最小 UI 端口。"""

    get_page: Callable[[], Optional[ft.Page]]
    refresh_stage: Callable[[], None]
    warn: DialogCallback
    info: DialogCallback
    error: DialogCallback
    handle_error: ErrorCallback
    log: LogCallback


@dataclass(frozen=True)
class NbtCommitMessages:
    """提交状态对应的本地化标题和正文。"""

    world_changed: tuple[str, str]
    busy: tuple[str, str]
    cancelled: tuple[str, str]
    queue_full: tuple[str, str]


@dataclass(frozen=True)
class _CommitRequest:
    """后台提交输入及其所属视图 generation。"""

    session: WorldSession
    changes: Tuple[NbtChange, ...]
    generation: int


class NbtCommitHandler:
    """负责提交预览、队列转换与会话刷新。"""

    def __init__(
        self,
        *,
        store: NbtStageStore,
        get_world_session: Callable[[], Optional[WorldSession]],
        execution: NbtCommitExecution,
        ui: NbtCommitUi,
        messages: NbtCommitMessages,
    ) -> None:
        """注入提交所需的会话与 UI 端口。"""
        self._store = store
        self._get_world_session = get_world_session
        self._execution = execution
        self._ui = ui
        self._messages = messages
        self._active_handle: Optional[OperationHandle[NbtCommitResult]] = None

    @property
    def is_committing(self) -> bool:
        """返回是否仍有提交任务等待 UI 消费终态。"""
        return self._active_handle is not None

    def commit_changes(self, e: object = None) -> None:
        """验证当前状态并打开提交预览。"""
        try:
            if not self._get_world_session():
                self._ui.warn("提示", "请先通过侧边栏设置当前存档。")
                return
            if not self._store:
                self._ui.info("提示", "暂存区没有可提交的变更。")
                return
            self.show_commit_preview_dialog()
        except Exception as ex:
            self._ui.handle_error(ex, "提交 NBT 变更失败")

    def show_commit_preview_dialog(self) -> None:
        """显示提交预览；无页面环境时直接提交。"""
        page = self._ui.get_page()
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

    def execute_commit(self) -> Optional[OperationHandle[NbtCommitResult]]:
        """验证快照并把完整提交非阻塞地交给共享 I/O 通道。"""
        try:
            if self._active_handle is not None:
                self._ui.warn(*self._messages.busy)
                return None
            session = self._get_world_session()
            if not session:
                self._ui.warn("提示", "请先通过侧边栏设置当前存档。")
                return None
            if not self._store:
                self._ui.info("提示", "暂存区没有可提交的变更。")
                return None
            if not self._execution.is_world_current(session.world_path):
                self._ui.warn(*self._messages.world_changed)
                return None

            request = _CommitRequest(
                session=session,
                changes=self._store.changes,
                generation=self._execution.get_generation(),
            )
            handle = self._execution.scope.submit(
                "commit_nbt_changes",
                lambda token: commit_nbt_changes(
                    request.session,
                    request.changes,
                    token,
                ),
                priority=TaskPriority.INTERACTIVE,
            )
            self._active_handle = handle
            handle.add_done_callback(
                lambda completed: self._execution.post_to_ui(
                    lambda: self._finish_commit(completed, request)
                )
            )
            return handle
        except (TaskQueueFullError, RuntimeClosedError):
            self._ui.warn(*self._messages.queue_full)
            return None
        except Exception as ex:
            self._ui.handle_error(ex, "提交 NBT 变更失败")
            return None

    def _finish_commit(
        self,
        handle: OperationHandle[NbtCommitResult],
        request: _CommitRequest,
    ) -> None:
        """在 UI 线程消费提交结果，并丢弃过期视图回调。"""
        if self._active_handle is handle:
            self._active_handle = None
        if not self._is_request_current(request):
            self._ui.log(
                f"丢弃过期 NBT 提交回调: {request.session.world_path}",
                "INFO",
            )
            return
        try:
            result = handle.result()
        except (CancelledError, OperationCancelledError):
            self._ui.warn(*self._messages.cancelled)
            return
        except Exception as ex:
            self._ui.handle_error(ex, "提交 NBT 变更失败")
            return
        if not result.committed:
            self._ui.error(
                "提交失败",
                f"已排队 {result.queued_operations} 个操作，但提交失败。请查看日志。",
            )
            return

        self._store.remove_snapshot(request.changes)
        self._ui.refresh_stage()
        try:
            self._execution.reload_world(result.world_path)
        except Exception as exc:
            # 磁盘事务已经成功，UI 刷新失败不能改写提交语义。
            self._ui.log(f"提交成功，但刷新世界会话失败: {exc}", "WARNING")
        self._ui.info(
            "提交完成",
            f"已提交 {result.requested_changes} 个 NBT/JSON/区块变更。"
            "提交前已创建备份。",
        )

    def _is_request_current(self, request: _CommitRequest) -> bool:
        """确认完成结果仍属于提交时的世界和视图 generation。"""
        return (
            request.generation == self._execution.get_generation()
            and self._execution.is_world_current(request.session.world_path)
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
