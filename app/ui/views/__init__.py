"""Views"""
from app.ui.views.migrator import MigratorView
from app.ui.views.explorer import ExplorerView
from app.ui.views.mappings import MappingsView
from app.ui.views.settings import SettingsView
from app.ui.views.compare import CompareView
from app.ui.views.server_properties import ServerPropertiesView

__all__ = [
    "MigratorView",
    "ExplorerView",
    "MappingsView",
    "SettingsView",
    "CompareView",
    "ServerPropertiesView",
]
