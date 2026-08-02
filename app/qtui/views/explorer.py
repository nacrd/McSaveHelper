"""Minecraft 存档浏览器（Qt 迁移版）。"""
from __future__ import annotations

import math
from os.path import normcase
from pathlib import Path
from typing import Protocol

from PySide6.QtWidgets import (
    QHBoxLayout,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.qtui.components.cards import muted_label, title_label
from app.qtui.context import (
    QtDialogPort,
    QtFileDialogPort,
    QtProgressPort,
    QtRuntimePort,
    QtTranslationPort,
)
from app.qtui.view_actions import QtViewAction
from app.qtui.views.explorer_tasks import (
    ExplorerTaskCallbacks,
    ExplorerTasks,
    ExplorerWorldSnapshot,
)
from app.qtui.views.entity_search_coordinator import (
    QtEntitySearchCoordinator,
)
from app.qtui.views.nbt_coordinator import QtNbtCoordinator
from app.qtui.views.player import QtPlayerPanel
from app.qtui.views.player_tasks import (
    PlayerDetailResult,
    PlayerTaskCallbacks,
    PlayerTasks,
)
from app.qtui.views.region_map_coordinator import QtRegionMapCoordinator
from app.qtui.views.stats_coordinator import QtStatsCoordinator
from app.qtui.views.world_info import QtWorldInfoPanel
from app.services.backup_service import BackupRecord, BackupService
from app.services.player.models import PlayerEditResult, PlayerRef
from app.services.player_service import PlayerService
from app.services.world_repository import WorldRepository
from app.services.world_stats_service import WorldStatsService
from app.core.save_context_manager import SaveContextManager
from app.qtui.view_manager import QtViewManager
from core.omni.world_session import WorldSession
from core.world_index import WorldShellMetadata
from core.world_index_progress import (
    WorldIndexBuildPhase,
    WorldIndexProgressFrame,
)


class ExplorerHost(
    QtTranslationPort,
    QtDialogPort,
    QtFileDialogPort,
    QtProgressPort,
    QtRuntimePort,
    Protocol,
):
    """Explorer 首批 Qt 页面所需的窄端口。"""

    @property
    def world_repository(self) -> WorldRepository:
        """返回应用共享世界读取仓库。"""
        ...

    @property
    def backup(self) -> BackupService:
        """返回应用共享备份服务。"""
        ...

    @property
    def world_stats(self) -> WorldStatsService:
        """返回应用共享世界统计服务。"""
        ...

    @property
    def save_context_manager(self) -> SaveContextManager:
        """返回当前存档上下文管理器。"""
        ...

    @property
    def view_manager(self) -> QtViewManager:
        """返回 Qt 视图管理器。"""
        ...

    @property
    def current_save_path(self) -> str | None:
        """返回当前选中的存档路径。"""
        ...


def map_index_progress(frame: WorldIndexProgressFrame) -> tuple[float, str]:
    """把索引构建帧映射为 0..100 的单调进度与阶段。"""
    if frame.phase is WorldIndexBuildPhase.VALIDATING:
        return 20.0, "validating"
    if frame.phase is WorldIndexBuildPhase.DISCOVERING:
        ratio = 1.0 - math.exp(-frame.discovered_files / 800.0)
        return 20.0 + 40.0 * ratio, "discovering"
    if frame.phase is WorldIndexBuildPhase.PROBING:
        total = frame.total or frame.completed
        fraction = frame.completed / total if total else 0.0
        return 60.0 + 32.0 * fraction, "probing"
    if frame.phase is WorldIndexBuildPhase.FINALIZING:
        return 92.0, "finalizing"
    return 95.0, "complete"


class ExplorerView(QWidget):
    """存档浏览器壳层：信息、玩家、区域地图、统计、搜索与 NBT。"""

    _TAB_KEYS = (
        ("explorer.tab_world_info", "存档信息"),
        ("explorer.tab_players", "玩家"),
        ("explorer.tab_map", "地图"),
        ("explorer.tab_stats", "统计"),
        ("explorer.tab_search", "搜索"),
        ("explorer.tab_nbt", "NBT"),
    )

    def __init__(self, app: ExplorerHost) -> None:
        """构建 Explorer 并创建世界读取任务所有者。

        Args:
            app: Explorer 所需的服务与 UI 端口。
        """
        super().__init__()
        self.app = app
        self.world_session: WorldSession | None = None
        self._loaded_world_path: Path | None = None
        self._disposed = False
        self._stats_coordinator = QtStatsCoordinator(app)
        self._search_coordinator = QtEntitySearchCoordinator(app)
        self._nbt_coordinator = QtNbtCoordinator(
            app,
            self._reload_after_nbt_commit,
        )
        self._region_map = QtRegionMapCoordinator(
            app,
            on_open_region_nbt=self._open_region_nbt,
            on_dimension_synced=self._nbt_coordinator.set_dimension,
        )
        self._build()
        self._tasks = ExplorerTasks(
            app.execution_runtime,
            app.world_repository,
            app.backup,
            app.log,
            ExplorerTaskCallbacks(
                shell_ready=self._apply_shell_metadata,
                index_progress=self._apply_index_progress,
                load_success=self._apply_loaded_world,
                load_error=self._apply_load_error,
                backup_progress=self._apply_backup_progress,
                backup_success=self._apply_backup_success,
                backup_error=self._apply_backup_error,
                backup_finished=self._finish_backup,
            ),
        )
        self._player_tasks = PlayerTasks(
            app.execution_runtime,
            self._player_service,
            PlayerTaskCallbacks(
                players_ready=self._apply_players,
                players_error=self._apply_players_error,
                detail_ready=self._apply_player_detail,
                detail_error=self._apply_player_detail_error,
                export_success=self._apply_player_export_success,
                export_error=self._apply_player_export_error,
            ),
        )

    def get_top_actions(self) -> list[QtViewAction]:
        """存档信息页操作位于内容区，顶栏无附加命令。"""
        return []

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        layout.addWidget(self._build_header())
        self._tabs = QTabWidget()
        self._world_info = QtWorldInfoPanel(
            self.app.translate,
            self.app.save_context_manager.on_import_save,
            self._create_backup,
            self._open_backup_center,
        )
        self._tabs.addTab(
            self._world_info,
            self._t("explorer.tab_world_info", "存档信息"),
        )
        self._players = QtPlayerPanel(
            self.app.translate,
            self._select_player,
            self._refresh_player_form,
            self._stage_player_form,
            self._stage_player_teleport,
            self._export_player_summary,
        )
        self._player_service = PlayerService(log=self.app.log)
        self._tabs.addTab(
            self._players,
            self._t("explorer.tab_players", "玩家"),
        )
        self._tabs.addTab(
            self._region_map.panel,
            self._t("explorer.tab_map", "地图"),
        )
        self._tabs.addTab(
            self._stats_coordinator.panel,
            self._t("explorer.tab_stats", "统计"),
        )
        self._tabs.addTab(
            self._search_coordinator.panel,
            self._t("explorer.tab_search", "搜索"),
        )
        self._tabs.addTab(
            self._nbt_coordinator.panel,
            self._t("explorer.tab_nbt", "NBT"),
        )
        layout.addWidget(self._tabs, 1)

    def _build_header(self) -> QWidget:
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 6)
        layout.setSpacing(14)
        layout.addWidget(title_label(
            f"⌕  {self._t('explorer.title', '存档浏览器')}"
        ))
        self._world_label = muted_label(self._t(
            "sidebar.no_current_save", "未设置当前存档"
        ))
        layout.addWidget(self._world_label)
        layout.addStretch(1)
        return header

    def _t(self, key: str, default: str = "", **kwargs: object) -> str:
        return self.app.translate(key, default, **kwargs)

    def did_mount(self) -> None:
        """首次挂载时加载已经由侧边栏选中的世界。"""
        current_path = self.app.current_save_path
        if current_path:
            self.on_save_selected(current_path)

    def on_save_selected(self, path: str) -> None:
        """切换当前世界并启动异步读取。"""
        if self._disposed or self._is_current_world(path):
            return
        try:
            world_path = Path(path).expanduser().resolve()
            self._loaded_world_path = world_path
            self.world_session = None
            self._player_tasks.clear_world()
            self._region_map.clear_world()
            self._stats_coordinator.clear_world()
            self._search_coordinator.clear_world()
            self._nbt_coordinator.clear_world()
            self._players.show_loading()
            self._world_label.setText(self._t(
                "explorer.loading_world", "正在加载存档..."
            ))
            self._world_info.show_loading(self._t(
                "explorer.opening_world", "正在打开存档目录..."
            ))
            self.app.show_progress(self._t(
                "explorer.loading_world", "正在加载存档..."
            ))
            self._tasks.load_world(world_path)
        except (OSError, RuntimeError, ValueError) as error:
            self._apply_load_error(error, self._tasks.load_generation)

    def _is_current_world(self, path: str) -> bool:
        if self._loaded_world_path is None:
            return False
        try:
            incoming = normcase(str(Path(path).expanduser().resolve()))
        except (OSError, RuntimeError, ValueError):
            return False
        return incoming == normcase(str(self._loaded_world_path))

    def _apply_shell_metadata(
        self,
        shell: WorldShellMetadata,
        generation: int,
    ) -> None:
        if not self._tasks.is_current_load(generation):
            return
        self._world_label.setText(self._t(
            "explorer.loading_summary",
            "{name} · 区域 {regions} · 维度提示 {dimensions} · 加载中...",
            name=shell.display_name,
            regions=shell.overworld_region_count,
            dimensions=shell.dimension_hint_count,
        ))

    def _apply_index_progress(
        self,
        frame: WorldIndexProgressFrame,
        generation: int,
    ) -> None:
        if not self._tasks.is_current_load(generation):
            return
        value, stage = map_index_progress(frame)
        if stage == "complete":
            return
        label = self._format_progress(frame, stage)
        self.app.update_progress_with_task(label, value)
        self._world_label.setText(f"{label} · {int(value)}%")

    def _format_progress(
        self,
        frame: WorldIndexProgressFrame,
        stage: str,
    ) -> str:
        if stage == "discovering":
            return self._t(
                "explorer.discovering",
                "正在发现文件 · {count} 个",
                count=frame.discovered_files,
            )
        if stage == "probing":
            return self._t(
                "explorer.probing",
                "正在读取文件属性 · {completed}/{total}",
                completed=frame.completed,
                total=frame.total or frame.completed,
            )
        keys = {
            "validating": ("explorer.validating", "正在校验存档目录..."),
            "finalizing": ("explorer.finalizing", "正在整理索引..."),
        }
        key, default = keys.get(
            stage, ("explorer.loading_world", "正在加载存档...")
        )
        return self._t(key, default)

    def _apply_loaded_world(
        self,
        snapshot: ExplorerWorldSnapshot,
        generation: int,
    ) -> None:
        if not self._tasks.is_current_load(generation):
            return
        self.world_session = snapshot.session
        self._loaded_world_path = snapshot.session.world_path
        self._world_label.setText(self._t(
            "explorer.current_world",
            "当前存档: {name}",
            name=snapshot.session.world_path.name,
        ))
        self._world_info.show_info(snapshot.world_info, snapshot.stats)
        self._players.show_loading()
        self._player_tasks.load_players(snapshot.session)
        self._region_map.set_world(snapshot.session)
        self._stats_coordinator.set_world(snapshot.session)
        self._search_coordinator.set_world(snapshot.session)
        self._nbt_coordinator.set_world(
            snapshot.session,
            dimension_id=self._region_map.current_dimension or "overworld",
        )
        self.app.hide_progress()

    def _apply_load_error(self, error: Exception, generation: int) -> None:
        if not self._tasks.is_current_load(generation):
            return
        self.world_session = None
        self._loaded_world_path = None
        self._player_tasks.clear_world()
        self._region_map.clear_world()
        self._stats_coordinator.clear_world()
        self._search_coordinator.clear_world()
        self._nbt_coordinator.clear_world()
        self._world_label.setText(self._t(
            "explorer.load_error", "加载存档失败"
        ))
        self._world_info.show_empty()
        self._players.show_empty()
        self.app.hide_progress()
        if isinstance(error, FileNotFoundError):
            title = self._t("explorer.invalid_world", "无效的存档")
            message = self._t(
                "explorer.invalid_world_message",
                "所选目录不是有效的 Minecraft 存档：\n\n{error}",
                error=error,
            )
        else:
            title = self._t("explorer.load_error", "加载存档失败")
            message = f"{type(error).__name__}: {error}"
        self.app.error_dialog(title, message)

    def on_save_cleared(self) -> None:
        """取消世界任务并恢复 Explorer 空状态。"""
        if self._disposed:
            return
        self._tasks.clear_world()
        self._player_tasks.clear_world()
        self._region_map.clear_world()
        self._stats_coordinator.clear_world()
        self._search_coordinator.clear_world()
        self._nbt_coordinator.clear_world()
        self.world_session = None
        self._loaded_world_path = None
        self.app.hide_progress()
        self._world_label.setText(self._t(
            "sidebar.no_current_save", "未设置当前存档"
        ))
        self._world_info.show_empty()
        self._players.show_empty()

    def _apply_players(
        self,
        players: tuple[PlayerRef, ...],
        generation: int,
    ) -> None:
        if self._player_tasks.is_current_world(generation):
            self._players.show_players(players)

    def _apply_players_error(
        self,
        error: Exception,
        generation: int,
    ) -> None:
        if not self._player_tasks.is_current_world(generation):
            return
        self._players.show_list_error()
        self.app.handle_exception(
            error,
            title=self._t("player.error.list", "加载玩家列表失败"),
        )

    def _select_player(self, uuid: str) -> None:
        session = self.world_session
        if session is None:
            return
        self._players.show_detail_loading(uuid)
        self._player_tasks.load_detail(session, uuid)

    def _apply_player_detail(
        self,
        detail: PlayerDetailResult,
        uuid: str,
        world_generation: int,
        detail_generation: int,
    ) -> None:
        if not self._player_tasks.is_current_detail(
            uuid, world_generation, detail_generation
        ):
            return
        if detail.summary is None and detail.player_data is None:
            self._players.show_detail_unavailable(uuid)
            return
        self._players.show_detail(detail)

    def _apply_player_detail_error(
        self,
        error: Exception,
        uuid: str,
        world_generation: int,
        detail_generation: int,
    ) -> None:
        if not self._player_tasks.is_current_detail(
            uuid, world_generation, detail_generation
        ):
            return
        self._players.show_detail_unavailable(uuid)
        self.app.handle_exception(
            error,
            title=self._t("player.error.load", "加载玩家数据失败"),
        )

    def _refresh_player_form(self) -> None:
        """从当前玩家 NBT 回填编辑表单。"""
        editor = self._players.editor
        if editor.player_data is None:
            self.app.warn_dialog(
                self._t("dialogs.hint", "提示"),
                self._t("player.need_select", "请先选择玩家。"),
            )
            return
        try:
            editor.refresh_form_from_data()
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self.app.handle_exception(
                error,
                title=self._t(
                    "player.error.refresh_form", "刷新玩家编辑表单失败"
                ),
            )

    def _stage_player_form(self) -> None:
        """把玩家表单差异暂存到共享 NBT 暂存区。"""
        uuid = self._players.current_uuid
        editor = self._players.editor
        player_data = editor.player_data
        if not uuid or player_data is None:
            self.app.warn_dialog(
                self._t("dialogs.hint", "提示"),
                self._t("player.need_select", "请先选择玩家。"),
            )
            return
        try:
            result = self._player_service.build_edit_changes(
                uuid,
                player_data,
                editor.collect_field_values(),
                specs=editor.active_specs(),
                target_label=(
                    f"{self._t('player.nbt_label', '玩家 NBT')}: {uuid}"
                ),
            )
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self.app.handle_exception(
                error,
                title=self._t("player.error.stage", "暂存玩家数据失败"),
            )
            return
        self._apply_player_stage_result(result)

    def _stage_player_teleport(self) -> None:
        """根据死亡位置暂存坐标传送变更。"""
        uuid = self._players.current_uuid
        editor = self._players.editor
        player_data = editor.player_data
        if not uuid or player_data is None:
            self.app.warn_dialog(
                self._t("dialogs.hint", "提示"),
                self._t("player.need_select", "请先选择玩家。"),
            )
            return
        try:
            result = self._player_service.build_teleport_to_death_changes(
                uuid,
                player_data,
                target_label=(
                    f"{self._t('player.nbt_label', '玩家 NBT')}: {uuid}"
                ),
            )
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self.app.handle_exception(
                error,
                title=self._t("player.error.teleport", "暂存传送失败"),
            )
            return
        if result.errors:
            self.app.warn_dialog(
                self._t("dialogs.hint", "提示"),
                self._t(
                    "player.no_death_location",
                    "当前玩家没有可用的死亡位置。",
                ),
            )
            return
        staged = self._nbt_coordinator.stage_external_changes(result.changes)
        if staged:
            self.app.info_dialog(
                self._t("player.edit.staged_title", "已暂存"),
                self._t(
                    "player.teleport_death_staged",
                    "已暂存传送到死亡点的坐标修改。",
                ),
            )
            self._tabs.setCurrentIndex(5)

    def _apply_player_stage_result(self, result: PlayerEditResult) -> None:
        if result.errors:
            self.app.warn_dialog(
                self._t("dialogs.hint", "提示"),
                self._t(
                    "player.edit.validation_errors",
                    "部分字段未暂存：{errors}",
                    errors=", ".join(result.errors),
                ),
            )
        if result.changes:
            self._nbt_coordinator.stage_external_changes(result.changes)
        if result.staged_count:
            self.app.info_dialog(
                self._t("player.edit.staged_title", "已暂存"),
                self._t(
                    "player.edit.staged_body",
                    "已暂存 {count} 个玩家数据修改，可到 NBT 页查看并提交。",
                    count=result.staged_count,
                ),
            )
            self._tabs.setCurrentIndex(5)
            return
        if not result.errors:
            self.app.info_dialog(
                self._t("dialogs.hint", "提示"),
                self._t(
                    "player.edit.no_changes",
                    "没有检测到需要暂存的玩家数据修改。",
                ),
            )

    def _export_player_summary(self) -> None:
        """弹出保存对话框并异步导出玩家摘要。"""
        session = self.world_session
        uuid = self._players.current_uuid
        if session is None or not uuid:
            self.app.warn_dialog(
                self._t("dialogs.hint", "提示"),
                self._t("player.need_select", "请先选择玩家。"),
            )
            return
        path = self.app.save_file(
            title=self._t("player.export_dialog", "导出玩家摘要"),
            default_ext=".json",
            file_types=[
                ("JSON", "*.json"),
                ("Text", "*.txt"),
            ],
        )
        if not path:
            return
        try:
            if not self._player_tasks.export_summary(
                session,
                uuid,
                Path(path),
                self.app.translate,
            ):
                self.app.warn_dialog(
                    self._t("dialogs.hint", "提示"),
                    self._t("player.need_select", "请先选择玩家。"),
                )
        except (OSError, RuntimeError, ValueError) as error:
            self.app.handle_exception(
                error,
                title=self._t("player.error.export", "导出玩家摘要失败"),
            )

    def _apply_player_export_success(
        self,
        output_path: Path,
        generation: int,
    ) -> None:
        del generation
        self.app.info_dialog(
            self._t("player.export_ok_title", "导出成功"),
            self._t(
                "player.export_ok_body",
                "已导出玩家摘要到：\n{path}",
                path=str(output_path),
            ),
        )

    def _apply_player_export_error(
        self,
        error: Exception,
        generation: int,
    ) -> None:
        del generation
        self.app.handle_exception(
            error,
            title=self._t("player.error.export", "导出玩家摘要失败"),
        )

    def _create_backup(self) -> None:
        session = self.world_session
        if session is None:
            self.app.warn_dialog(
                self._t("dialogs.warning", "提示"),
                self._t("explorer.load_first", "请先加载存档"),
            )
            return
        if not self._tasks.start_backup(session):
            self.app.warn_dialog(
                self._t("dialogs.warning", "提示"),
                self._t(
                    "explorer.backup_running",
                    "快速备份正在进行中，请稍候",
                ),
            )
            return
        self._world_info.set_backup_busy(True)
        self.app.show_progress(self._t(
            "explorer.backup_progress", "正在创建备份..."
        ))

    def _apply_backup_progress(
        self,
        message: str,
        value: float,
        generation: int,
    ) -> None:
        del generation
        self.app.update_progress_with_task(message, value * 100.0)

    def _apply_backup_success(
        self,
        record: BackupRecord,
        generation: int,
    ) -> None:
        del generation
        self.app.info_dialog(
            self._t("dialogs.success", "成功"),
            self._t(
                "explorer.backup_success",
                "备份已创建：{path}",
                path=record.backup_path,
            ),
        )

    def _apply_backup_error(
        self,
        error: Exception,
        generation: int,
    ) -> None:
        del generation
        self.app.handle_exception(error, title=self._t(
            "explorer.backup_error", "创建备份失败"
        ))

    def _finish_backup(self, generation: int) -> None:
        del generation
        self._world_info.set_backup_busy(False)
        self.app.hide_progress()

    def _open_backup_center(self) -> None:
        self.app.view_manager.switch_view("backup_center")

    def _open_region_nbt(
        self,
        region_x: int,
        region_z: int,
        dimension_id: str,
    ) -> None:
        """从地图选区打开区块 NBT 标签页。"""
        self._nbt_coordinator.set_dimension(dimension_id)
        self._nbt_coordinator.open_region_chunk(
            region_x,
            region_z,
            dimension_id=dimension_id,
        )
        self._tabs.setCurrentIndex(5)

    def _reload_after_nbt_commit(self, world_path: Path) -> None:
        """提交发布后强制重建 Explorer 的不可变世界读会话。"""
        if self._disposed:
            return
        self._loaded_world_path = None
        self.on_save_selected(str(world_path))

    def dispose(self) -> None:
        """取消 Explorer 页面任务；可重复调用。"""
        if self._disposed:
            return
        self._disposed = True
        self._loaded_world_path = None
        self.world_session = None
        self._nbt_coordinator.close()
        self._search_coordinator.close()
        self._region_map.close()
        self._stats_coordinator.close()
        self._player_tasks.close()
        self._tasks.close()


__all__ = ["ExplorerHost", "ExplorerView", "map_index_progress"]
