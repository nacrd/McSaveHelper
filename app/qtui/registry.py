"""Qt 顶层功能注册表：侧边栏目录与惰性视图工厂（对应 Flet 版 feature_registry）。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from PySide6.QtWidgets import QWidget

from app.qtui.context import QtFeatureContext

ViewFactory = Callable[[QtFeatureContext], QWidget]
Translate = Callable[..., str]


@dataclass(frozen=True)
class QtFeatureDescriptor:
    """一个 Qt 顶层功能的导航与工厂描述。"""

    view_id: str
    translation_key: str
    default_label: str
    icon_glyph: str
    factory: ViewFactory

    def sidebar_definition(self, translate: Translate) -> dict[str, str]:
        """构造已翻译的侧边栏条目。"""
        return {
            "id": self.view_id,
            "label": translate(self.translation_key, self.default_label),
            "icon": self.icon_glyph,
        }


@dataclass(frozen=True)
class QtNavigationDescriptor:
    """一个侧边栏入口及其目标视图/工作区。"""

    navigation_id: str
    view_id: str
    group_key: str
    group_label: str
    translation_key: str
    default_label: str
    icon_glyph: str
    workspace_id: str = ""
    placement: str = "main"

    def sidebar_definition(self, translate: Translate) -> dict[str, str]:
        """构造侧边栏使用的已翻译入口。"""
        return {
            "id": self.navigation_id,
            "view_id": self.view_id,
            "workspace_id": self.workspace_id,
            "group_id": self.group_key,
            "group": translate(self.group_key, self.group_label),
            "label": translate(self.translation_key, self.default_label),
            "icon": self.icon_glyph,
            "placement": self.placement,
        }


class QtFeatureRegistry:
    """维护 Qt 顶层功能声明的稳定顺序与唯一性。"""

    def __init__(
        self,
        features: tuple[QtFeatureDescriptor, ...],
        navigation: tuple[QtNavigationDescriptor, ...] | None = None,
    ) -> None:
        """校验并保存功能描述。

        Args:
            features: 功能描述序列。

        Raises:
            ValueError: 功能 id 为空或重复。
        """
        identifiers = [feature.view_id for feature in features]
        if not features or len(identifiers) != len(set(identifiers)):
            raise ValueError("Qt 功能注册表必须包含唯一的功能 id")
        self._features = features
        self._by_id: dict[str, QtFeatureDescriptor] = {
            feature.view_id: feature for feature in features
        }
        self._navigation = navigation or self._navigation_from_features(features)
        navigation_ids = [item.navigation_id for item in self._navigation]
        if len(navigation_ids) != len(set(navigation_ids)):
            raise ValueError("Qt 导航注册表必须包含唯一的导航 id")
        unknown_views = {
            item.view_id for item in self._navigation if item.view_id not in self._by_id
        }
        if unknown_views:
            raise ValueError(f"Qt 导航引用了未注册视图: {sorted(unknown_views)}")
        self._navigation_by_id = {
            item.navigation_id: item for item in self._navigation
        }

    @property
    def features(self) -> tuple[QtFeatureDescriptor, ...]:
        """返回注册顺序稳定的功能描述。"""
        return self._features

    def get(self, view_id: str) -> Optional[QtFeatureDescriptor]:
        """按 id 返回功能描述。"""
        return self._by_id.get(view_id)

    @property
    def navigation(self) -> tuple[QtNavigationDescriptor, ...]:
        """返回稳定顺序的导航入口。"""
        return self._navigation

    def get_navigation(
        self,
        navigation_id: str,
    ) -> Optional[QtNavigationDescriptor]:
        """按导航 id 返回入口描述。"""
        return self._navigation_by_id.get(navigation_id)

    def default_navigation_for_view(
        self,
        view_id: str,
    ) -> Optional[QtNavigationDescriptor]:
        """返回目标视图的首个导航入口。"""
        return next(
            (item for item in self._navigation if item.view_id == view_id),
            None,
        )

    def sidebar_definitions(self, translate: Translate) -> list[dict[str, str]]:
        """构造稳定顺序的侧边栏定义。"""
        return [
            item.sidebar_definition(translate)
            for item in self._navigation
        ]

    @staticmethod
    def _navigation_from_features(
        features: tuple[QtFeatureDescriptor, ...],
    ) -> tuple[QtNavigationDescriptor, ...]:
        """为测试和扩展注册表生成兼容的默认导航。"""
        return tuple(
            QtNavigationDescriptor(
                navigation_id=feature.view_id,
                view_id=feature.view_id,
                group_key="sidebar.group_tools",
                group_label="工具",
                translation_key=feature.translation_key,
                default_label=feature.default_label,
                icon_glyph=feature.icon_glyph,
            )
            for feature in features
        )


def _default_registry() -> QtFeatureRegistry:
    """构建默认 Qt 功能注册表。

    仅包含已完成迁移的视图；后续阶段逐个追加，避免半成品标签进入侧边栏。
    """
    from app.qtui.views.backup_center import BackupCenterView
    from app.qtui.views.compare import CompareView
    from app.qtui.views.explorer import ExplorerView
    from app.qtui.views.mappings import MappingsView
    from app.qtui.views.migrator import MigratorView
    from app.qtui.views.save_repair import SaveRepairView
    from app.qtui.views.server_properties import ServerPropertiesView

    features = (
        QtFeatureDescriptor(
            view_id="explorer",
            translation_key="sidebar.explorer",
            default_label="存档浏览器",
            icon_glyph="⌕",
            factory=lambda ctx: ExplorerView(ctx),
        ),
        QtFeatureDescriptor(
            view_id="migrator",
            translation_key="sidebar.migrator",
            default_label="存档转换",
            icon_glyph="⇄",
            factory=lambda ctx: MigratorView(ctx),
        ),
        QtFeatureDescriptor(
            view_id="save_repair",
            translation_key="sidebar.save_repair",
            default_label="存档修复",
            icon_glyph="🧱",
            factory=lambda ctx: SaveRepairView(ctx),
        ),
        QtFeatureDescriptor(
            view_id="backup_center",
            translation_key="sidebar.backup_center",
            default_label="备份与恢复",
            icon_glyph="🕐",
            factory=lambda ctx: BackupCenterView(ctx),
        ),
        QtFeatureDescriptor(
            view_id="compare",
            translation_key="sidebar.compare",
            default_label="存档对比",
            icon_glyph="⚖️",
            factory=lambda ctx: CompareView(ctx),
        ),
        QtFeatureDescriptor(
            view_id="mappings",
            translation_key="sidebar.mappings",
            default_label="映射管理",
            icon_glyph="🔗",
            factory=lambda ctx: MappingsView(ctx),
        ),
        QtFeatureDescriptor(
            view_id="settings",
            translation_key="sidebar.settings",
            default_label="设置",
            icon_glyph="⚙️",
            factory=lambda ctx: ctx.create_settings_view(),
        ),
        QtFeatureDescriptor(
            view_id="server_properties",
            translation_key="sidebar.server_properties",
            default_label="服务器配置",
            icon_glyph="📄",
            factory=lambda ctx: ServerPropertiesView(ctx),
        ),
    )
    navigation = (
        QtNavigationDescriptor(
            "world_overview", "explorer", "sidebar.group_world", "世界",
            "explorer.tab_world_info", "概览", "🗂", "world_info",
        ),
        QtNavigationDescriptor(
            "world_players", "explorer", "sidebar.group_world", "世界",
            "explorer.tab_players", "玩家", "🧍", "players",
        ),
        QtNavigationDescriptor(
            "world_map", "explorer", "sidebar.group_world", "世界",
            "explorer.tab_map", "地图", "🗺", "map",
        ),
        QtNavigationDescriptor(
            "world_stats", "explorer", "sidebar.group_world", "世界",
            "explorer.tab_stats", "统计", "📊", "stats",
        ),
        QtNavigationDescriptor(
            "world_search", "explorer", "sidebar.group_world", "世界",
            "explorer.tab_search", "搜索", "🔎", "search",
        ),
        QtNavigationDescriptor(
            "world_nbt", "explorer", "sidebar.group_world", "世界",
            "explorer.tab_nbt", "NBT", "📝", "nbt",
        ),
        QtNavigationDescriptor(
            "backup_center", "backup_center", "sidebar.group_safety",
            "安全与维护", "sidebar.backup_center", "备份与恢复", "🕐",
        ),
        QtNavigationDescriptor(
            "save_repair", "save_repair", "sidebar.group_safety",
            "安全与维护", "sidebar.save_repair", "存档修复", "🧱",
        ),
        QtNavigationDescriptor(
            "migrator", "migrator", "sidebar.group_diagnostics",
            "转换与诊断", "sidebar.migrator", "存档转换", "⇄",
        ),
        QtNavigationDescriptor(
            "compare", "compare", "sidebar.group_diagnostics",
            "转换与诊断", "sidebar.compare", "存档对比", "⚖",
        ),
        QtNavigationDescriptor(
            "mappings", "mappings", "sidebar.group_tools", "工具",
            "sidebar.mappings", "映射管理", "🔗",
        ),
        QtNavigationDescriptor(
            "server_properties", "server_properties", "sidebar.group_tools",
            "工具", "sidebar.server_properties", "服务器配置", "📄",
        ),
        QtNavigationDescriptor(
            "settings", "settings", "sidebar.group_tools", "工具",
            "sidebar.settings", "设置", "⚙", placement="footer",
        ),
    )
    return QtFeatureRegistry(features, navigation)


def create_qt_registry() -> QtFeatureRegistry:
    """创建默认 Qt 功能注册表。"""
    return _default_registry()
