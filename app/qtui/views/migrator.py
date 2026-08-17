"""Minecraft 存档迁移视图（Qt 版）。"""
from __future__ import annotations

from typing import Protocol

from PySide6.QtWidgets import (
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.qtui.components.layout import page_header
from app.qtui.context import (
    QtDialogPort,
    QtMigrationPort,
    QtRuntimePort,
    QtTranslationPort,
)
from app.qtui.view_actions import QtViewAction
from app.qtui.views.migrator_options import (
    format_uuid_query_result,
    mode_description,
    version_downgrade_warning,
)
from app.qtui.views.migrator_sections import (
    build_batch_section,
    build_directory_section,
    build_mode_section,
    build_options_section,
    build_player_section,
    build_version_section,
)
from app.qtui.views.migrator_tasks import (
    BatchScanResult,
    MigratorTaskCallbacks,
    MigratorTasks,
    UuidQueryResult,
)
from app.services.config_service import ConfigService
from app.services.migration_service import MigrationService
from app.services.uuid_service import UUIDService


class MigratorHost(
    QtTranslationPort,
    QtDialogPort,
    QtRuntimePort,
    QtMigrationPort,
    Protocol,
):
    """迁移页面所需的服务与 UI 端口。"""

    @property
    def config(self) -> ConfigService:
        """返回应用配置服务。"""
        ...

    @property
    def migration(self) -> MigrationService:
        """返回迁移服务。"""
        ...

    @property
    def uuid(self) -> UUIDService:
        """返回 UUID 服务。"""
        ...


class MigratorView(QScrollArea):
    """配置并启动单世界或批量迁移。"""

    def __init__(self, app: MigratorHost) -> None:
        """构建迁移表单并创建页面级后台任务作用域。

        Args:
            app: 页面所需的迁移、配置、运行时和 UI 端口。
        """
        super().__init__()
        self.app = app
        self._disposed = False
        self._start_enabled = True
        self.setWidgetResizable(True)
        self._build()
        self._tasks = MigratorTasks(
            app.execution_runtime,
            app.migration,
            app.uuid,
            app.log,
            MigratorTaskCallbacks(
                batch_success=self._apply_batch_scan_success,
                batch_error=self._apply_batch_scan_error,
                query_success=self._apply_uuid_query_success,
                query_error=self._apply_uuid_query_error,
            ),
        )

    def get_top_actions(self) -> list[QtViewAction]:
        """返回开始和取消迁移命令。"""
        return [
            QtViewAction(
                self._t("top_bar.start_conversion", "开始转换"),
                self._start,
                enabled=self._start_enabled,
            ),
            QtViewAction(
                self._t("top_bar.cancel_migration", "取消迁移"),
                self._cancel,
                "danger",
                enabled=not self._start_enabled,
            ),
        ]

    def _build(self) -> None:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(24)
        layout.addWidget(page_header(
            "存档转换",
            "跨版本迁移世界、玩家数据、UUID 和资源映射",
            icon="⇄",
        ))
        # 布局：按转换决策顺序分步展示，避免全部配置同时占据首屏。
        layout.addWidget(self._build_workflow_tabs())
        layout.addStretch(1)
        self.setWidget(content)

    def _build_workflow_tabs(self) -> QTabWidget:
        config = self.app.config.migration
        self._directory = build_directory_section(
            config,
            self._sync_config,
            self.app.migration_commands.choose_destination,
        )
        self._version = build_version_section(config, self._on_version_change)
        self._mode = build_mode_section(config, self._on_mode_change)
        self._options = build_options_section(config, self._sync_config)
        self._player = build_player_section(
            config,
            self._sync_config,
            self._query_uuid,
        )
        self._batch = build_batch_section(
            config,
            self._sync_config,
            self._toggle_batch,
            self.app.migration_commands.choose_batch_directory,
            self._scan_batch,
        )

        tabs = QTabWidget()
        tabs.addTab(
            self._tab_page(self._directory.card, self._version.card),
            self._t("migrator.step_paths", "1  路径与版本"),
        )
        tabs.addTab(
            self._tab_page(self._mode.card, self._options.card),
            self._t("migrator.step_mode", "2  模式与选项"),
        )
        tabs.addTab(
            self._tab_page(self._player.card),
            self._t("migrator.step_players", "3  玩家与 UUID"),
        )
        tabs.addTab(
            self._tab_page(self._batch.card),
            self._t("migrator.step_batch", "批量转换"),
        )
        return tabs

    @staticmethod
    def _tab_page(*widgets: QWidget) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        for widget in widgets:
            layout.addWidget(widget)
        layout.addStretch(1)
        return page

    def _t(self, key: str, default: str = "", **kwargs: object) -> str:
        return self.app.translate(key, default, **kwargs)

    def _start(self) -> None:
        if self._disposed or not self._start_enabled:
            return
        self._sync_config()
        self.app.migration_commands.start()

    def _cancel(self) -> None:
        if self._disposed:
            return
        if self.app.migration_commands.cancel():
            self.app.log(
                self._t(
                    "messages.migration_cancel_requested",
                    "已请求取消迁移",
                ),
                "WARNING",
            )
            return
        self.app.warn_dialog(
            self._t("dialogs.warning", "提示"),
            self._t(
                "messages.no_migration_running",
                "当前没有运行中的迁移任务",
            ),
        )

    def set_start_enabled(self, enabled: bool) -> None:
        """同步组合根持有的开始命令状态。"""
        self._start_enabled = enabled

    def set_path_value(self, target: str, value: str) -> None:
        """通过公开命令边界更新路径字段。

        Args:
            target: ``source``、``destination`` 或 ``batch``。
            value: 新路径。

        Raises:
            ValueError: 目标名称未知。
        """
        fields = {
            "source": self._directory.source,
            "destination": self._directory.destination,
            "batch": self._batch.directory,
        }
        try:
            field = fields[target]
        except KeyError as error:
            raise ValueError(f"未知路径目标: {target}") from error
        field.setText(value)
        self._sync_config()

    def _sync_config(self) -> None:
        config = self.app.config.migration
        config.src_path = self._directory.source.text().strip()
        config.dest_path = self._directory.destination.text().strip()
        config.world_name = self._directory.world_name.text().strip() or "world"
        config.target_platform = str(
            self._version.platform.currentData() or "java"
        )
        config.target_version = self._target_version()
        config.manual_names = self._player.manual_names.text().strip()
        config.offline_mode = self._options.offline.isChecked()
        config.clean_mode = self._options.clean.isChecked()
        config.pure_clean_mode = self._options.pure_clean.isChecked()
        config.batch_mode = self._batch.enabled.isChecked()
        config.batch_dir_path = self._batch.directory.text().strip()

    def _target_version(self) -> str:
        data = self._version.version.currentData()
        if data is not None and self._version.version.currentIndex() == 0:
            return str(data)
        return self._version.version.currentText().strip()

    def _on_mode_change(self, mode: str) -> None:
        config = self.app.config.migration
        config.mode = mode
        is_fast = mode == "fast"
        self._mode.description.setText(mode_description(mode))
        self._version.strip_components.setEnabled(not is_fast)
        self._version.replace_unknown.setEnabled(not is_fast)
        if is_fast:
            self._version.warning.setVisible(False)
        else:
            self._update_version_warning()

    def _on_version_change(self) -> None:
        self._sync_config()
        self._update_version_warning()

    def _update_version_warning(self) -> None:
        if self.app.config.migration.mode == "fast":
            self._version.warning.setVisible(False)
            return
        try:
            target_version = int(self._target_version())
        except ValueError:
            self._version.warning.setVisible(False)
            return
        warning = version_downgrade_warning(target_version)
        self._version.warning.setText(warning or "")
        self._version.warning.setVisible(bool(warning))
        if warning:
            self._version.strip_components.setChecked(True)
            self._version.replace_unknown.setChecked(True)

    def _toggle_batch(self, enabled: bool) -> None:
        self._batch.details.setVisible(enabled)
        self._sync_config()

    def _scan_batch(self) -> None:
        if self._disposed:
            return
        self._sync_config()
        directory = self.app.config.migration.batch_dir_path
        self._batch.scan_button.setEnabled(False)
        self._tasks.scan(directory)

    def _apply_batch_scan_success(
        self,
        result: BatchScanResult,
        directory: str,
        generation: int,
    ) -> None:
        if not self._is_current_scan(directory, generation):
            return
        self._batch.scan_button.setEnabled(True)
        if result.worlds:
            self._batch.result.setText(result.message)
            self.app.log(
                self._t(
                    "messages.batch_scan_complete",
                    "批量扫描完成: 找到 {count} 个世界存档",
                    count=len(result.worlds),
                ),
                "SUCCESS",
            )
            return
        self._batch.result.setText(self._t(
            "messages.no_valid_worlds", "未找到有效的世界存档"
        ))
        self.app.log(
            self._t(
                "messages.batch_scan_no_worlds",
                "批量扫描: 未找到有效的世界存档",
            ),
            "WARN",
        )

    def _apply_batch_scan_error(
        self,
        error: Exception,
        directory: str,
        generation: int,
    ) -> None:
        if not self._is_current_scan(directory, generation):
            return
        self._batch.scan_button.setEnabled(True)
        self.app.handle_exception(error, title="批量扫描失败")

    def _is_current_scan(self, directory: str, generation: int) -> bool:
        return (
            not self._disposed
            and self._tasks.is_current_scan(generation)
            and self._batch.directory.text().strip() == directory
        )

    def _query_uuid(self) -> None:
        if self._disposed:
            return
        name = self._player.query_name.text().strip()
        if not name:
            self._tasks.invalidate_query()
            self._player.query_result.setText("在此显示查询结果")
            return
        self._player.query_button.setEnabled(False)
        self._player.query_result.setText("正在查询 UUID...")
        self._tasks.query(name)

    def _apply_uuid_query_success(
        self,
        result: UuidQueryResult,
        name: str,
        generation: int,
    ) -> None:
        if not self._is_current_query(name, generation):
            return
        self._player.query_button.setEnabled(True)
        self._player.query_result.setText(format_uuid_query_result(
            name,
            result.offline_uuid,
            result.online_uuid,
            result.official_name,
        ))

    def _apply_uuid_query_error(
        self,
        error: Exception,
        name: str,
        generation: int,
    ) -> None:
        if not self._is_current_query(name, generation):
            return
        self._player.query_button.setEnabled(True)
        self._player.query_result.setText("UUID 查询失败，请稍后重试。")
        self.app.handle_exception(error, title="UUID 查询失败")

    def _is_current_query(self, name: str, generation: int) -> bool:
        return (
            not self._disposed
            and self._tasks.is_current_query(generation)
            and self._player.query_name.text().strip() == name
        )

    def on_save_selected(self, path: str) -> None:
        """同步侧边栏当前存档到迁移源路径。"""
        self.set_path_value("source", path)

    def on_save_cleared(self) -> None:
        """清空迁移源路径。"""
        self.set_path_value("source", "")

    def dispose(self) -> None:
        """取消页面任务并拒绝释放后的迟到结果。"""
        if self._disposed:
            return
        self._disposed = True
        self._tasks.close()
