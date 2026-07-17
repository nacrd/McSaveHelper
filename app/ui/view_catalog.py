"""Default UI view registrations for the desktop application."""
from app.core.view_catalog import ViewCatalog


def create_default_view_catalog() -> ViewCatalog:
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
    catalog.register_lazy("settings", "app.ui.views.settings", "SettingsView")
    return catalog
