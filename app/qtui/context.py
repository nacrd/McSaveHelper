"""Qt 视图端口协议与上下文（对应 Flet 树 ``app/ui/feature_context.py``）。

Qt 视图只依赖本模块定义的端口，不依赖 ``app.ui`` 或 ``flet``。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional, Protocol

from app.adapters.file_dialogs import FileType

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from app.core.save_context_manager import SaveContextManager
    from app.services.backup_service import BackupService
    from app.services.cache_registry import CacheRegistry
    from app.services.config_service import ConfigService
    from app.services.execution_runtime import ExecutionRuntime
    from app.services.item_service import ItemService
    from app.services.migration_service import MigrationService
    from app.services.region_map import RegionMapService
    from app.services.save_repair_service import SaveRepairService
    from app.services.texture_service import TextureService
    from app.services.ui_delivery import UiDeliveryPort
    from app.services.uuid_service import UUIDService
    from app.services.world_compare_service import WorldCompareService
    from app.services.world_repository import WorldRepository
    from app.services.world_stats_service import WorldStatsService
    from app.services.world_transaction import WorldTransactionService
    from app.qtui.view_manager import QtViewManager
    from core.omni.world_session import WorldSession


class QtTranslationPort(Protocol):
    """翻译与轻量日志端口。"""

    def translate(self, key: str, default: str = "", **kwargs: Any) -> str:
        """翻译 UI 文本。"""
        ...

    def log(self, msg: str, level: str = "INFO") -> None:
        """写入应用日志。"""
        ...


class QtDialogPort(Protocol):
    """模态通知与异常呈现端口。"""

    def info_dialog(self, title: str, message: str) -> None:
        """展示信息对话框。"""
        ...

    def warn_dialog(self, title: str, message: str) -> None:
        """展示警告对话框。"""
        ...

    def error_dialog(
        self,
        title: str,
        message: str,
        exception: Optional[Exception] = None,
        show_details: bool = False,
    ) -> None:
        """展示错误对话框。"""
        ...

    def handle_exception(
        self,
        exception: Exception,
        title: Optional[str] = None,
        log: bool = True,
        show_dialog: bool = True,
    ) -> None:
        """处理异常。"""
        ...


class QtFileDialogPort(Protocol):
    """文件与目录选择端口。"""

    def pick_directory(self) -> Optional[str]:
        """选择目录。"""
        ...

    def pick_file(
        self,
        title: str = "",
        file_types: Optional[list[FileType]] = None,
    ) -> Optional[str]:
        """选择单个文件。"""
        ...

    def pick_files(
        self,
        title: str = "",
        file_types: Optional[list[FileType]] = None,
    ) -> Optional[list[str]]:
        """选择多个文件。"""
        ...

    def save_file(
        self,
        title: str = "",
        default_ext: str = ".txt",
        file_types: Optional[list[FileType]] = None,
    ) -> Optional[str]:
        """另存为对话框。"""
        ...


class QtProgressPort(Protocol):
    """共享进度呈现端口。"""

    def show_progress(self, task_name: str = "") -> None:
        """显示进度。"""
        ...

    def hide_progress(self) -> None:
        """隐藏进度。"""
        ...

    def update_progress_with_task(self, task_name: str, value: float) -> None:
        """更新命名进度。"""
        ...


class QtFeedbackPort(Protocol):
    """非阻塞全局反馈端口。"""

    def show_status_message(self, message: str, timeout_ms: int = 5000) -> None:
        """在主窗口状态栏显示短暂消息。"""
        ...


class QtRuntimePort(Protocol):
    """后台执行运行时端口。"""

    @property
    def execution_runtime(self) -> ExecutionRuntime:
        """返回共享执行运行时。"""
        ...


class QtMigrationPort(Protocol):
    """迁移页面使用的窄命令端口。"""

    @property
    def migration_commands(self) -> "QtMigrationCommands":
        """返回迁移命令集合。"""
        ...


class QtMapPort(Protocol):
    """地图服务工厂端口。"""

    def create_region_map_service(self) -> RegionMapService:
        """创建地图服务。"""
        ...


class QtUuidMappingPort(Protocol):
    """UUID 映射持久化端口。"""

    def update_uuid_mappings(self, mappings: dict[str, str]) -> None:
        """持久化 UUID 映射。"""
        ...


class QtHost(
    QtTranslationPort,
    QtDialogPort,
    QtFileDialogPort,
    QtFeedbackPort,
    QtProgressPort,
    QtRuntimePort,
    QtMigrationPort,
    QtMapPort,
    QtUuidMappingPort,
    Protocol,
):
    """组合宿主：Qt 视图所需的全部 UI 与服务端口。"""

    @property
    def current_save_path(self) -> Optional[str]:
        """返回当前选中存档路径。"""
        ...

    @property
    def config(self) -> ConfigService:
        """配置服务。"""
        ...

    @property
    def migration(self) -> MigrationService:
        """迁移服务。"""
        ...

    @property
    def uuid(self) -> UUIDService:
        """UUID 服务。"""
        ...

    @property
    def item(self) -> ItemService:
        """物品服务。"""
        ...

    @property
    def texture(self) -> TextureService:
        """纹理服务。"""
        ...

    @property
    def ui_delivery(self) -> "UiDeliveryPort":
        """框架中立的 UI 结果投递端口。"""
        ...

    @property
    def backup(self) -> BackupService:
        """备份服务。"""
        ...

    @property
    def save_repair(self) -> SaveRepairService:
        """存档修复服务。"""
        ...

    @property
    def world_compare(self) -> WorldCompareService:
        """存档对比服务。"""
        ...

    @property
    def world_transactions(self) -> WorldTransactionService:
        """世界事务服务。"""
        ...

    @property
    def world_repository(self) -> WorldRepository:
        """世界读取仓库。"""
        ...

    @property
    def world_stats(self) -> WorldStatsService:
        """世界统计服务。"""
        ...

    @property
    def cache_registry(self) -> CacheRegistry:
        """缓存注册表。"""
        ...

    @property
    def save_context_manager(self) -> SaveContextManager:
        """存档上下文管理器。"""
        ...

    @property
    def view_manager(self) -> "QtViewManager":
        """视图管理器。"""
        ...

    def create_settings_view(self) -> QWidget:
        """构建设置视图（由组合根提供端口）。"""
        ...

    def navigate_to(self, navigation_id: str) -> None:
        """切换到侧边栏导航入口。"""
        ...

    def set_world_context_status(self, status: str, detail: str = "") -> None:
        """更新全局世界上下文状态。"""
        ...

    def set_navigation_badge(self, navigation_id: str, count: int) -> None:
        """更新侧边栏导航待办徽标。"""
        ...


@dataclass(frozen=True)
class QtFeatureContext:
    """Qt 视图的受限端口包。"""

    host: QtHost

    @property
    def execution_runtime(self) -> ExecutionRuntime:
        return self.host.execution_runtime

    @property
    def ui_delivery(self) -> "UiDeliveryPort":
        return self.host.ui_delivery

    @property
    def config(self) -> ConfigService:
        return self.host.config

    @property
    def migration(self) -> MigrationService:
        return self.host.migration

    @property
    def uuid(self) -> UUIDService:
        return self.host.uuid

    @property
    def item(self) -> ItemService:
        return self.host.item

    @property
    def texture(self) -> TextureService:
        return self.host.texture

    @property
    def backup(self) -> BackupService:
        return self.host.backup

    @property
    def save_repair(self) -> SaveRepairService:
        return self.host.save_repair

    @property
    def world_compare(self) -> WorldCompareService:
        return self.host.world_compare

    @property
    def world_transactions(self) -> WorldTransactionService:
        return self.host.world_transactions

    @property
    def world_repository(self) -> WorldRepository:
        return self.host.world_repository

    @property
    def world_stats(self) -> WorldStatsService:
        return self.host.world_stats

    @property
    def cache_registry(self) -> CacheRegistry:
        return self.host.cache_registry

    @property
    def current_save_path(self) -> Optional[str]:
        return self.host.current_save_path

    @property
    def save_context_manager(self) -> SaveContextManager:
        return self.host.save_context_manager

    @property
    def view_manager(self) -> "QtViewManager":
        return self.host.view_manager

    @property
    def migration_commands(self) -> "QtMigrationCommands":
        """返回迁移页面可用的应用级命令。"""
        return self.host.migration_commands

    def translate(self, key: str, default: str = "", **kwargs: Any) -> str:
        return self.host.translate(key, default, **kwargs)

    def log(self, msg: str, level: str = "INFO") -> None:
        self.host.log(msg, level)

    def info_dialog(self, title: str, message: str) -> None:
        self.host.info_dialog(title, message)

    def warn_dialog(self, title: str, message: str) -> None:
        self.host.warn_dialog(title, message)

    def error_dialog(
        self,
        title: str,
        message: str,
        exception: Optional[Exception] = None,
        show_details: bool = False,
    ) -> None:
        self.host.error_dialog(title, message, exception, show_details)

    def handle_exception(
        self,
        exception: Exception,
        title: Optional[str] = None,
        log: bool = True,
        show_dialog: bool = True,
    ) -> None:
        self.host.handle_exception(exception, title, log, show_dialog)

    def show_status_message(self, message: str, timeout_ms: int = 5000) -> None:
        """显示非阻塞全局反馈。"""
        self.host.show_status_message(message, timeout_ms)

    def pick_directory(self) -> Optional[str]:
        return self.host.pick_directory()

    def pick_file(
        self,
        title: str = "",
        file_types: Optional[list[FileType]] = None,
    ) -> Optional[str]:
        return self.host.pick_file(title, file_types)

    def pick_files(
        self,
        title: str = "",
        file_types: Optional[list[FileType]] = None,
    ) -> Optional[list[str]]:
        return self.host.pick_files(title, file_types)

    def save_file(
        self,
        title: str = "",
        default_ext: str = ".txt",
        file_types: Optional[list[FileType]] = None,
    ) -> Optional[str]:
        return self.host.save_file(title, default_ext, file_types)

    def show_progress(self, task_name: str = "") -> None:
        self.host.show_progress(task_name)

    def hide_progress(self) -> None:
        self.host.hide_progress()

    def update_progress_with_task(self, task_name: str, value: float) -> None:
        self.host.update_progress_with_task(task_name, value)

    def create_region_map_service(self) -> RegionMapService:
        return self.host.create_region_map_service()

    def create_settings_view(self) -> QWidget:
        """构建设置视图。"""
        return self.host.create_settings_view()

    def navigate_to(self, navigation_id: str) -> None:
        """切换到侧边栏导航入口。"""
        self.host.navigate_to(navigation_id)

    def set_world_context_status(self, status: str, detail: str = "") -> None:
        """更新全局世界上下文状态。"""
        self.host.set_world_context_status(status, detail)

    def set_navigation_badge(self, navigation_id: str, count: int) -> None:
        """更新侧边栏导航待办徽标。"""
        self.host.set_navigation_badge(navigation_id, count)

    def update_uuid_mappings(self, mappings: dict[str, str]) -> None:
        self.host.update_uuid_mappings(mappings)

    def open_world_session(
        self,
        world_path: Path | str,
        *,
        log: Optional[Callable[[str, str], None]] = None,
    ) -> "WorldSession":
        """打开带共享仓库写端口的存档会话。"""
        return self.world_repository.open_session(world_path, log=log or self.log)


@dataclass(frozen=True)
class QtMigrationCommands:
    """由 Qt 组合根拥有的迁移命令集合。"""

    start: Callable[[], None]
    cancel: Callable[[], bool]
    choose_destination: Callable[[], None]
    choose_batch_directory: Callable[[], None]


__all__ = [
    "QtDialogPort",
    "QtFeatureContext",
    "QtFeedbackPort",
    "QtFileDialogPort",
    "QtHost",
    "QtMapPort",
    "QtMigrationCommands",
    "QtMigrationPort",
    "QtProgressPort",
    "QtRuntimePort",
    "QtTranslationPort",
    "QtUuidMappingPort",
]
