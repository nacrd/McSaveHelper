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


class QtFeatureRegistry:
    """维护 Qt 顶层功能声明的稳定顺序与唯一性。"""

    def __init__(self, features: tuple[QtFeatureDescriptor, ...]) -> None:
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

    @property
    def features(self) -> tuple[QtFeatureDescriptor, ...]:
        """返回注册顺序稳定的功能描述。"""
        return self._features

    def get(self, view_id: str) -> Optional[QtFeatureDescriptor]:
        """按 id 返回功能描述。"""
        return self._by_id.get(view_id)

    def sidebar_definitions(self, translate: Translate) -> list[dict[str, str]]:
        """构造稳定顺序的侧边栏定义。"""
        return [
            feature.sidebar_definition(translate)
            for feature in self._features
        ]


def _default_registry() -> QtFeatureRegistry:
    """构建默认 Qt 功能注册表。

    仅包含已完成迁移的视图；后续阶段逐个追加，避免半成品标签进入侧边栏。
    """
    from app.qtui.views.server_properties import ServerPropertiesView

    return QtFeatureRegistry(
        (
            QtFeatureDescriptor(
                view_id="server_properties",
                translation_key="sidebar.server_properties",
                default_label="服务器配置",
                icon_glyph="📄",
                factory=lambda ctx: ServerPropertiesView(ctx),
            ),
        )
    )


def create_qt_registry() -> QtFeatureRegistry:
    """创建默认 Qt 功能注册表。"""
    return _default_registry()
