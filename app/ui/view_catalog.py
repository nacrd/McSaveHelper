"""Default UI view registrations for the desktop application."""
from typing import Optional

from app.core.view_catalog import ViewCatalog, ViewFactory
from app.ui.feature_registry import DEFAULT_FEATURE_REGISTRY


def create_default_view_catalog(
    settings_factory: Optional[ViewFactory] = None,
    available_capabilities: Optional[frozenset[str]] = None,
) -> ViewCatalog:
    """创建默认视图目录，并允许组合根替换设置页构造方式。"""
    return DEFAULT_FEATURE_REGISTRY.create_view_catalog(
        settings_factory=settings_factory,
        available_capabilities=available_capabilities,
    )
