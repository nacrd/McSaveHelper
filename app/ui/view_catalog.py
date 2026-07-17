"""Default UI view registrations for the desktop application."""
from typing import Optional

from app.core.view_catalog import ViewCatalog, ViewFactory


def create_default_view_catalog(
    settings_factory: Optional[ViewFactory] = None,
) -> ViewCatalog:
    """创建默认视图目录，并允许组合根替换设置页构造方式。"""
    catalog = ViewCatalog()
    catalog.register_lazy(
        "explorer",
        "app.ui.views.explorer",
        "ExplorerView",
    )
    catalog.register_lazy("migrator", "app.ui.views.migrator", "MigratorView")
    catalog.register_lazy(
        "save_repair",
        "app.ui.views.save_repair",
        "SaveRepairView",
    )
    catalog.register_lazy(
        "map_export",
        "app.ui.views.map_export",
        "MapExportView",
    )
    catalog.register_lazy("compare", "app.ui.views.compare", "CompareView")
    catalog.register_lazy(
        "server_properties",
        "app.ui.views.server_properties",
        "ServerPropertiesView",
    )
    catalog.register_lazy("mappings", "app.ui.views.mappings", "MappingsView")
    if settings_factory is None:
        catalog.register_lazy(
            "settings",
            "app.ui.views.settings",
            "SettingsView",
        )
    else:
        catalog.register("settings", settings_factory)
    return catalog
