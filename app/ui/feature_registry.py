"""顶层功能的单一声明与惰性视图注册。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Optional, cast

import flet as ft

from app.core.view_catalog import (
    LazyViewFactory,
    TopActionsFactory,
    ViewCatalog,
    ViewFactory,
)
from app.ui.icons import IconSet
from app.ui.view_actions import ViewAction


Translate = Callable[..., str]


def _view_top_actions(view: object) -> Iterable[ViewAction]:
    """Adapt the public view-action protocol to a registered factory."""
    provider = getattr(view, "get_top_actions", None)
    if not callable(provider):
        return ()
    return cast(Iterable[ViewAction], provider())


@dataclass(frozen=True)
class FeatureDescriptor:
    """一个顶层功能的导航、翻译和视图工厂描述。"""

    view_id: str
    translation_key: str
    default_label: str
    icon: ft.IconData
    module: str | ViewFactory = ""
    class_name: str | TopActionsFactory = ""
    required_capabilities: frozenset[str] = frozenset()
    view_factory: Optional[ViewFactory] = None
    top_actions_factory: Optional[TopActionsFactory] = None

    def __post_init__(self) -> None:
        """Materialize explicit factories while keeping lazy view imports."""
        if self.view_factory is None and callable(self.module):
            object.__setattr__(
                self,
                "view_factory",
                cast(ViewFactory, self.module),
            )
            if self.top_actions_factory is None and callable(self.class_name):
                object.__setattr__(
                    self,
                    "top_actions_factory",
                    cast(TopActionsFactory, self.class_name),
                )
            object.__setattr__(self, "module", "")
            object.__setattr__(self, "class_name", "")
        if self.view_factory is None:
            module = self.module
            class_name = self.class_name
            if (
                not isinstance(module, str)
                or not module
                or not isinstance(class_name, str)
                or not class_name
            ):
                raise ValueError(
                    "view_factory or module/class_name must be provided"
                )
            object.__setattr__(
                self,
                "view_factory",
                LazyViewFactory(module, class_name),
            )
        if self.top_actions_factory is None:
            object.__setattr__(self, "top_actions_factory", _view_top_actions)

    def sidebar_definition(self, translate: Translate) -> dict[str, object]:
        """构造已翻译的侧边栏条目。"""
        return {
            "id": self.view_id,
            "label": translate(self.translation_key, self.default_label),
            "icon": self.icon,
        }

    def has_capabilities(self, available: frozenset[str]) -> bool:
        """当前能力集合是否满足本功能声明的依赖。"""
        return self.required_capabilities.issubset(available)

    def register(self, catalog: ViewCatalog) -> None:
        """在目录中注册功能的惰性视图工厂。"""
        view_factory = self.view_factory
        top_actions_factory = self.top_actions_factory
        if view_factory is None or top_actions_factory is None:
            raise RuntimeError("feature factories are not initialized")
        catalog.register(
            self.view_id,
            view_factory,
            top_actions_factory=top_actions_factory,
        )


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

    @property
    def capabilities(self) -> frozenset[str]:
        """返回注册功能声明的完整能力集合。"""
        return frozenset(
            capability
            for feature in self._features
            for capability in feature.required_capabilities
        )

    def available_features(
        self,
        available_capabilities: Optional[frozenset[str]] = None,
    ) -> tuple[FeatureDescriptor, ...]:
        """按能力筛选功能；未提供能力集时保持全部功能可用。"""
        if available_capabilities is None:
            return self._features
        return tuple(
            feature
            for feature in self._features
            if feature.has_capabilities(available_capabilities)
        )

    def sidebar_definitions(
        self,
        translate: Translate,
        available_capabilities: Optional[frozenset[str]] = None,
    ) -> list[dict[str, object]]:
        """构造稳定顺序的侧边栏定义。"""
        return [
            feature.sidebar_definition(translate)
            for feature in self.available_features(available_capabilities)
        ]

    def create_view_catalog(
        self,
        settings_factory: Optional[ViewFactory] = None,
        available_capabilities: Optional[frozenset[str]] = None,
    ) -> ViewCatalog:
        """注册全部惰性视图，并可替换设置页组合根工厂。"""
        catalog = ViewCatalog()
        for feature in self.available_features(available_capabilities):
            if feature.view_id == "settings" and settings_factory is not None:
                catalog.register(
                    feature.view_id,
                    settings_factory,
                    top_actions_factory=feature.top_actions_factory,
                )
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
            frozenset({"map.tiles", "world.read", "world.write"}),
        ),
        FeatureDescriptor(
            "migrator",
            "sidebar.migrator",
            "存档转换",
            IconSet.PACKAGE,
            "app.ui.views.migrator",
            "MigratorView",
            frozenset({"world.migrate", "world.read", "world.write"}),
        ),
        FeatureDescriptor(
            "save_repair",
            "sidebar.save_repair",
            "存档修复",
            IconSet.BUILD,
            "app.ui.views.save_repair",
            "SaveRepairView",
            frozenset({"world.read", "world.repair", "world.write"}),
        ),
        FeatureDescriptor(
            "backup_center",
            "sidebar.backup_center",
            "备份与恢复",
            IconSet.HISTORY,
            "app.ui.views.backup_center",
            "BackupCenterView",
            frozenset({"world.backup", "world.read", "world.write"}),
        ),
        FeatureDescriptor(
            "compare",
            "sidebar.compare",
            "存档对比",
            IconSet.BALANCE,
            "app.ui.views.compare",
            "CompareView",
            frozenset({"world.compare", "world.read"}),
        ),
        FeatureDescriptor(
            "mappings",
            "sidebar.mappings",
            "映射管理",
            IconSet.LINK,
            "app.ui.views.mappings",
            "MappingsView",
            frozenset({"mappings.manage"}),
        ),
        FeatureDescriptor(
            "server_properties",
            "sidebar.server_properties",
            "服务器配置",
            IconSet.CLIPBOARD,
            "app.ui.views.server_properties",
            "ServerPropertiesView",
            frozenset({"server.properties"}),
        ),
        FeatureDescriptor(
            "settings",
            "sidebar.settings",
            "设置",
            IconSet.SETTINGS,
            "app.ui.views.settings",
            "SettingsView",
            frozenset({"app.settings"}),
        ),
    )
)


__all__ = [
    "DEFAULT_FEATURE_REGISTRY",
    "FeatureDescriptor",
    "FeatureRegistry",
]
