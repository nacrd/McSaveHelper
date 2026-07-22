"""Migrator View —— 存档转换主界面"""
from __future__ import annotations

from concurrent.futures import CancelledError
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import flet as ft

from app.services.execution_runtime import (
    ExecutionLane,
    OperationCancelledError,
    OperationHandle,
    TaskPriority,
)
from app.ui.components.layout import page_header
from app.ui.icons import IconSet
from app.ui.theme import THEME
from app.ui.utils import run_on_ui, safe_update
from app.ui.view_actions import ViewAction
from app.ui.views.migrator_cards import (
    build_batch_card,
    build_directory_card,
    build_guide_card,
    build_mode_card,
    build_options_card,
    build_player_card,
    build_version_card,
)
from app.ui.views.migrator_options import (
    format_uuid_query_result,
    mode_description,
    version_downgrade_warning,
)

if TYPE_CHECKING:
    from app.ui.feature_context import FeatureContext


@dataclass(frozen=True)
class _BatchScanResult:
    """后台批量扫描结果，避免 UI 回调读取服务的可变中间状态。"""

    worlds: tuple[Path, ...]
    message: str


@dataclass(frozen=True)
class _UuidQueryResult:
    """后台 UUID 查询结果。"""

    offline_uuid: str
    online_uuid: str | None
    official_name: str | None


class MigratorView(ft.Column):
    """存档转换视图 — 左右两栏布局（优化版）"""

    def __init__(self, app: "FeatureContext") -> None:
        """初始化存档转换视图。

        Args:
            app: 应用组合根，提供迁移服务与 UI 回调。
        """
        super().__init__(spacing=24, scroll=ft.ScrollMode.AUTO)
        self.expand = True
        self.app: "FeatureContext" = app
        self._task_scope = app.execution_runtime.create_scope("migrator_view")
        self._scan_generation = 0
        self._query_generation = 0
        self._query_handle: OperationHandle[_UuidQueryResult] | None = None
        self._build()

    @property
    def _t(self):
        return self.app.translate

    def get_top_actions(self) -> list[ViewAction]:
        """返回应用壳层顶栏可消费的视图命令。

        Returns:
            list[ViewAction]: 开始转换与取消批量处理等动作。
        """
        return [
            ViewAction(
                self._t("top_bar.start_conversion", "开始转换"),
                lambda event: self.app.migration_commands.start(),
            ),
            ViewAction(
                self._t("top_bar.cancel_migration", "取消迁移"),
                self._cancel_migration,
                "danger",
            ),
        ]

    def _cancel_migration(self, event: ft.ControlEvent) -> None:
        del event
        if self.app.migration_commands.cancel():
            self.app.log(
                self._t(
                    "messages.migration_cancel_requested",
                    "已请求取消迁移",
                ),
                "WARNING",
            )
        else:
            self.app.warn_dialog(
                self._t("dialogs.warning", "提示"),
                self._t(
                    "messages.no_migration_running",
                    "当前没有运行中的迁移任务",
                ),
            )

    def set_path_value(self, target: str, value: str) -> None:
        """Update a path control through the public view command boundary."""
        fields = {
            "source": self._src_field,
            "destination": self._dest_field,
            "batch": self._batch_dir_field,
        }
        try:
            field = fields[target]
        except KeyError as error:
            raise ValueError(f"未知路径目标: {target}") from error
        field.value = value
        try:
            field.update()
        except RuntimeError:
            pass

    def _build(self) -> None:
        self.controls.clear()
        self._page_header = page_header(
            "存档转换",
            ft.Text(
                "跨版本迁移世界、玩家数据、UUID 和资源映射",
                size=12,
                color=THEME.text_muted,
            ),
            icon=IconSet.PACKAGE,
        )
        self.controls.append(self._page_header)
        self.controls.append(build_guide_card())
        self._left_content = self._build_left()
        self._right_content = self._build_right()
        self._content_gap = ft.Container(width=24)
        content = ft.Row(
            [self._left_content, self._content_gap, self._right_content],
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )
        self._content_host = ft.Container(content=content)
        self.controls.append(self._content_host)

    def set_compact_mode(self, compact: bool) -> None:
        """Stack migration cards vertically when two columns cannot fit."""
        host = getattr(self, "_content_host", None)
        if host is None:
            return
        if compact:
            self._left_content.expand = False
            self._right_content.expand = False
            host.content = ft.Column(
                [self._left_content, self._right_content],
                spacing=16,
            )
        else:
            self._left_content.expand = True
            self._right_content.expand = True
            host.content = ft.Row(
                [self._left_content, self._content_gap, self._right_content],
                expand=True,
                vertical_alignment=ft.CrossAxisAlignment.START,
            )
        safe_update(host)

    def _build_left(self) -> ft.Column:
        mc = self.app.config.migration
        col = ft.Column(spacing=24)
        col.expand = True

        directory = build_directory_card(
            translate=self._t,
            src_path=mc.src_path or "",
            dest_path=mc.dest_path or "",
            world_name=mc.world_name or "world",
            on_field_change=self._sync_field_to_config,
            on_browse_dest=self.app.migration_commands.choose_destination,
        )
        self._src_field = directory.src_field
        self._dest_field = directory.dest_field
        self._name_field = directory.name_field
        col.controls.append(directory.container)

        version = build_version_card(
            target_platform=mc.target_platform or "java",
            target_version=mc.target_version or "",
            on_platform_change=lambda value: setattr(
                self.app.config.migration, "target_platform", value
            ),
            on_version_change=self._on_version_change,
        )
        self._vc_platform_dd = version.platform_dd
        self._vc_version_dd = version.version_dd
        self._vc_strip_cb = version.strip_cb
        self._vc_replace_cb = version.replace_cb
        self._vc_warn_box = version.warn_box
        col.controls.append(version.container)

        player = build_player_card(
            translate=self._t,
            manual_names=mc.manual_names or "",
            on_field_change=self._sync_field_to_config,
            on_query_uuid=self._query_uuid,
        )
        self._manual_field = player.manual_field
        self._query_field = player.query_field
        self._query_result = player.query_result
        col.controls.append(player.container)
        return col

    def _build_right(self) -> ft.Column:
        mc = self.app.config.migration
        col = ft.Column(spacing=24)
        col.expand = True

        mode = build_mode_card(
            translate=self._t,
            mode=mc.mode or "fast",
            on_mode_change=self._on_mode_change,
        )
        self._mode_group = mode.mode_group
        self._mode_desc = mode.mode_desc
        col.controls.append(mode.container)

        options = build_options_card(
            translate=self._t,
            offline_mode=mc.offline_mode,
            clean_mode=mc.clean_mode,
            pure_clean_mode=mc.pure_clean_mode,
            on_offline_change=lambda value: setattr(
                self.app.config.migration, "offline_mode", value
            ),
            on_clean_change=lambda value: setattr(
                self.app.config.migration, "clean_mode", value
            ),
            on_pure_clean_change=lambda value: setattr(
                self.app.config.migration, "pure_clean_mode", value
            ),
        )
        self._offline_cb = options.offline_cb
        self._clean_cb = options.clean_cb
        self._pure_clean_cb = options.pure_clean_cb
        col.controls.append(options.container)

        batch = build_batch_card(
            translate=self._t,
            batch_mode=mc.batch_mode,
            batch_dir_path=mc.batch_dir_path or "",
            on_toggle_batch=self._toggle_batch,
            on_field_change=self._sync_field_to_config,
            on_browse_batch=(
                self.app.migration_commands.choose_batch_directory
            ),
            on_scan_batch=self._scan_batch,
        )
        self._batch_mode_cb = batch.batch_mode_cb
        self._batch_dir_field = batch.batch_dir_field
        self._batch_scan_btn = batch.batch_scan_btn
        self._batch_result = batch.batch_result
        self._batch_detail_col = batch.batch_detail_col
        col.controls.append(batch.container)
        return col

    def _on_mode_change(self, mode: str) -> None:
        mc = self.app.config.migration
        mc.mode = mode
        is_fast = mode == "fast"
        self._mode_desc.value = mode_description(mode)
        self._vc_strip_cb.disabled = is_fast
        self._vc_replace_cb.disabled = is_fast
        if is_fast:
            self._vc_warn_box.visible = False
        else:
            self._on_version_update()
        self.update()

    def _on_version_change(self) -> None:
        self.app.config.migration.target_version = self._vc_version_dd.value or ""
        self._on_version_update()
        self.update()

    def _on_version_update(self) -> None:
        if (self._mode_group.value or "fast") == "fast":
            return
        try:
            target_ver = int(self._vc_version_dd.value or "0")
        except (ValueError, TypeError):
            return
        warning = version_downgrade_warning(target_ver)
        if warning:
            self._vc_warn_box.value = warning
            self._vc_warn_box.visible = True
            self._vc_strip_cb.value = True
            self._vc_replace_cb.value = True
        else:
            self._vc_warn_box.visible = False

    def _toggle_batch(self, enabled: bool) -> None:
        self.app.config.migration.batch_mode = enabled
        self._batch_detail_col.visible = enabled
        safe_update(self._batch_detail_col)

    def _sync_field_to_config(self) -> None:
        mc = self.app.config.migration
        mc.src_path = self._src_field.value or ""
        mc.dest_path = self._dest_field.value or ""
        mc.world_name = self._name_field.value or "world"
        mc.batch_dir_path = self._batch_dir_field.value or ""
        mc.manual_names = self._manual_field.value or ""
        mc.target_platform = self._vc_platform_dd.value or "java"
        mc.target_version = self._vc_version_dd.value or ""

    def _scan_batch(self) -> None:
        mc = self.app.config.migration
        directory = mc.batch_dir_path
        self._scan_generation += 1
        generation = self._scan_generation
        try:
            handle = self._task_scope.submit(
                "scan_batch_dir",
                lambda token: self._scan_batch_worker(directory, token),
                lane=ExecutionLane.IO,
                priority=TaskPriority.INTERACTIVE,
            )
            handle.add_done_callback(
                lambda completed: self._finish_batch_scan(
                    completed,
                    directory,
                    generation,
                )
            )
        except Exception as error:
            self._post_to_ui(
                self._apply_batch_scan_error,
                error,
                directory,
                generation,
            )

    def _scan_batch_worker(self, directory: str, token: object) -> _BatchScanResult:
        """在 I/O 通道扫描批量存档目录。"""
        raise_if_cancelled = getattr(token, "raise_if_cancelled", None)
        if callable(raise_if_cancelled):
            raise_if_cancelled()
        worlds = tuple(self.app.migration.scan_batch_dir(directory))
        if callable(raise_if_cancelled):
            raise_if_cancelled()
        return _BatchScanResult(worlds, self.app.migration.scan_result)

    def _finish_batch_scan(
        self,
        handle: OperationHandle[_BatchScanResult],
        directory: str,
        generation: int,
    ) -> None:
        if handle.cancelled:
            return
        try:
            result = handle.result()
        except (CancelledError, OperationCancelledError):
            return
        except Exception as error:
            self._post_to_ui(
                self._apply_batch_scan_error,
                error,
                directory,
                generation,
            )
            return
        self._post_to_ui(
            self._apply_batch_scan_success,
            result,
            directory,
            generation,
        )

    def _apply_batch_scan_success(
        self,
        result: _BatchScanResult,
        directory: str,
        generation: int,
    ) -> None:
        if generation != self._scan_generation:
            return
        if (self._batch_dir_field.value or "") != directory:
            return
        if result.worlds:
            self._batch_result.value = result.message
            self.app.log(
                self._t(
                    "messages.batch_scan_complete",
                    "批量扫描完成: 找到 {count} 个世界存档",
                    count=len(result.worlds),
                ),
                "SUCCESS",
            )
        else:
            self._batch_result.value = self._t(
                "messages.no_valid_worlds",
                "未找到有效的世界存档",
            )
            self.app.log(
                self._t(
                    "messages.batch_scan_no_worlds",
                    "批量扫描: 未找到有效的世界存档",
                ),
                "WARN",
            )
        safe_update(self._batch_result)

    def _apply_batch_scan_error(
        self,
        error: Exception,
        directory: str,
        generation: int,
    ) -> None:
        if generation != self._scan_generation:
            return
        if (self._batch_dir_field.value or "") != directory:
            return
        self.app.handle_exception(error, title="批量扫描失败")

    def _post_to_ui(self, callback: object, *args: object) -> None:
        """投递后台结果；无页面时供隔离测试直接执行。"""
        if not callable(callback):
            return
        page = getattr(self.app, "page", None)
        if page is None:
            callback(*args)
            return
        run_on_ui(page, callback, *args)

    def _query_uuid(self) -> None:
        name = (self._query_field.value or "").strip()
        self._query_generation += 1
        generation = self._query_generation
        previous_handle = self._query_handle
        self._query_handle = None
        if previous_handle is not None:
            previous_handle.cancel()
        if not name:
            self._query_result.value = "在此显示查询结果"
            safe_update(self._query_result)
            return

        self._query_result.value = "正在查询 UUID..."
        safe_update(self._query_result)
        try:
            handle = self._task_scope.submit(
                "query_uuid",
                lambda token: self._query_uuid_worker(name, token),
                lane=ExecutionLane.IO,
                priority=TaskPriority.INTERACTIVE,
            )
            self._query_handle = handle
            handle.add_done_callback(
                lambda completed: self._finish_uuid_query(
                    completed,
                    name,
                    generation,
                )
            )
        except Exception as error:
            self._post_to_ui(
                self._apply_uuid_query_error,
                error,
                name,
                generation,
            )

    def _query_uuid_worker(
        self,
        name: str,
        token: object,
    ) -> _UuidQueryResult:
        """在 I/O 通道生成离线 UUID 并查询 Mojang 服务。"""
        raise_if_cancelled = getattr(token, "raise_if_cancelled", None)
        if callable(raise_if_cancelled):
            raise_if_cancelled()
        offline_uuid = self.app.uuid.generate_offline_uuid(name)
        if callable(raise_if_cancelled):
            raise_if_cancelled()
        online_uuid, official_name = self.app.uuid.query_online_uuid(
            name,
            self.app.log,
        )
        if callable(raise_if_cancelled):
            raise_if_cancelled()
        return _UuidQueryResult(
            offline_uuid=offline_uuid,
            online_uuid=online_uuid,
            official_name=official_name,
        )

    def _finish_uuid_query(
        self,
        handle: OperationHandle[_UuidQueryResult],
        name: str,
        generation: int,
    ) -> None:
        if handle.cancelled:
            return
        try:
            result = handle.result()
        except (CancelledError, OperationCancelledError):
            return
        except Exception as error:
            self._post_to_ui(
                self._apply_uuid_query_error,
                error,
                name,
                generation,
            )
            return
        self._post_to_ui(
            self._apply_uuid_query_success,
            result,
            name,
            generation,
        )

    def _apply_uuid_query_success(
        self,
        result: _UuidQueryResult,
        name: str,
        generation: int,
    ) -> None:
        if not self._is_current_uuid_query(name, generation):
            return
        self._query_handle = None
        self._query_result.value = format_uuid_query_result(
            name,
            result.offline_uuid,
            result.online_uuid,
            result.official_name,
        )
        safe_update(self._query_result)

    def _apply_uuid_query_error(
        self,
        error: Exception,
        name: str,
        generation: int,
    ) -> None:
        if not self._is_current_uuid_query(name, generation):
            return
        self._query_handle = None
        self._query_result.value = "UUID 查询失败，请稍后重试。"
        safe_update(self._query_result)
        self.app.handle_exception(error, title="UUID 查询失败")

    def _is_current_uuid_query(self, name: str, generation: int) -> bool:
        return (
            generation == self._query_generation
            and (self._query_field.value or "").strip() == name
        )

    def on_save_selected(self, path: str) -> None:
        """响应侧边栏「当前存档」变更，同步源路径字段。

        Args:
            path: 新选中的存档目录路径。
        """
        try:
            self._src_field.value = path
            self._sync_field_to_config()
        except Exception:
            # UI best-effort: field/config sync may fail during teardown.
            pass
        safe_update(self._src_field)

    def dispose(self) -> None:
        """释放视图自有任务；应用级迁移控制器由组合根关闭。"""
        self._scan_generation += 1
        self._query_generation += 1
        self._query_handle = None
        self._task_scope.close()
