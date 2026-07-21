"""顶层功能的单一声明与惰性视图注册。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import flet as ft

from app.core.view_catalog import ViewCatalog, ViewFactory
from app.ui.icons import IconSet


Translate = Callable[..., str]


@dataclass(frozen=True)
class FeatureDescriptor:
    """一个顶层功能的导航、翻译和视图工厂描述。"""

    view_id: str
    translation_key: str
    default_label: str
    icon: ft.IconData
    module: str
    class_name: str

    def sidebar_definition(self, translate: Translate) -> dict[str, object]:
        """构造已翻译的侧边栏条目。"""
        return {
            "id": self.view_id,
            "label": translate(self.translation_key, self.default_label),
            "icon": self.icon,
        }

    def register(self, catalog: ViewCatalog) -> None:
        """在目录中注册功能的惰性视图工厂。"""
        catalog.register_lazy(self.view_id, self.module, self.class_name)


class FeatureRegistry:
    """维护顶层功能声明的稳定顺序与唯一性。"""

    def __init__(self, features: tuple[FeatureDescriptor, ...]) -> None:
        """校验并保存功能描述。"""
        identifiers = [feature.view_id for feature in features]
        if not features or len(identifiers) != len(set(identifiers)):
            raise ValueError("功能注册表必须包含唯一的功能 id")
        self._features = features

    @property
    def features(self) -> tuple[FeatureDescriptor, ...]:
        """返回注册顺序稳定的功能描述。"""
        return self._features

    def sidebar_definitions(
        self,
        translate: Translate,
    ) -> list[dict[str, object]]:
        """构造稳定顺序的侧边栏定义。"""
        return [
            feature.sidebar_definition(translate) for feature in self._features
        ]

    def create_view_catalog(
        self,
        settings_factory: Optional[ViewFactory] = None,
    ) -> ViewCatalog:
        """注册全部惰性视图，并可替换设置页组合根工厂。"""
        catalog = ViewCatalog()
        for feature in self._features:
            if feature.view_id == "settings" and settings_factory is not None:
                catalog.register(feature.view_id, settings_factory)
            else:
                feature.register(catalog)
        return catalog


DEFAULT_FEATURE_REGISTRY = FeatureRegistry(
    (
        FeatureDescriptor(
            "explorer",
            "sidebar.explorer",
            "存档浏览器",
            IconSet.MAP,
            "app.ui.views.explorer",
            "ExplorerView",
        ),
        FeatureDescriptor(
            "migrator",
            "sidebar.migrator",
            "存档转换",
            IconSet.PACKAGE,
            "app.ui.views.migrator",
            "MigratorView",
        ),
        FeatureDescriptor(
            "save_repair",
            "sidebar.save_repair",
            "存档修复",
            IconSet.BUILD,
            "app.ui.views.save_repair",
            "SaveRepairView",
        ),
        FeatureDescriptor(
            "backup_center",
            "sidebar.backup_center",
            "备份与恢复",
            IconSet.HISTORY,
            "app.ui.views.backup_center",
            "BackupCenterView",
        ),
        FeatureDescriptor(
            "compare",
            "sidebar.compare",
            "存档对比",
            IconSet.BALANCE,
            "app.ui.views.compare",
            "CompareView",
        ),
        FeatureDescriptor(
            "mappings",
            "sidebar.mappings",
            "映射管理",
            IconSet.LINK,
            "app.ui.views.mappings",
            "MappingsView",
        ),
        FeatureDescriptor(
            "server_properties",
            "sidebar.server_properties",
            "服务器配置",
            IconSet.CLIPBOARD,
            "app.ui.views.server_properties",
            "ServerPropertiesView",
        ),
        FeatureDescriptor(
            "settings",
            "sidebar.settings",
            "设置",
            IconSet.SETTINGS,
            "app.ui.views.settings",
            "SettingsView",
        ),
    )
)


__all__ = [
    "DEFAULT_FEATURE_REGISTRY",
    "FeatureDescriptor",
    "FeatureRegistry",
]
