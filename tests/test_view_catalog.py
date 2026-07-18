import pytest

from app.core.view_catalog import ViewCatalog
from app.ui.view_catalog import create_default_view_catalog


def test_catalog_creates_registered_view_with_application() -> None:
    catalog = ViewCatalog()
    application = object()
    created = object()
    catalog.register("test", lambda app: created if app is application else None)

    assert catalog.create("test", application) is created
    assert catalog.view_ids == ("test",)


def test_catalog_rejects_duplicate_and_unknown_views() -> None:
    catalog = ViewCatalog()
    catalog.register("test", lambda app: app)

    with pytest.raises(ValueError, match="视图已注册"):
        catalog.register("test", lambda app: app)
    with pytest.raises(KeyError, match="未注册的视图"):
        catalog.create("missing", object())


def test_default_catalog_contains_all_sidebar_views() -> None:
    catalog = create_default_view_catalog()

    assert set(catalog.view_ids) == {
        "explorer",
        "migrator",
        "save_repair",
        "backup_center",
        "map_export",
        "compare",
        "server_properties",
        "mappings",
        "settings",
    }
