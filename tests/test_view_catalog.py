import pytest
import flet as ft

from app.core.view_catalog import ViewCatalog
from app.ui.feature_registry import (
    DEFAULT_FEATURE_REGISTRY,
    FeatureDescriptor,
    FeatureRegistry,
)
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


def test_catalog_uses_registered_top_actions_factory() -> None:
    catalog = ViewCatalog()
    view = object()
    catalog.register(
        "test",
        lambda _context: view,
        top_actions_factory=lambda current_view: (
            "registered" if current_view is view else "wrong",
        ),
    )

    created = catalog.create("test", object())

    assert catalog.get_top_actions("test", created) == ("registered",)
    with pytest.raises(KeyError, match="未注册的视图"):
        catalog.get_top_actions("missing", created)


def test_default_catalog_contains_all_sidebar_views() -> None:
    catalog = create_default_view_catalog()

    assert set(catalog.view_ids) == {
        "explorer",
        "migrator",
        "save_repair",
        "backup_center",
        "compare",
        "server_properties",
        "mappings",
        "settings",
    }


def test_feature_registry_keeps_sidebar_and_view_catalog_in_lockstep() -> None:
    registry = FeatureRegistry((
        FeatureDescriptor(
            "first",
            "sidebar.first",
            "第一个",
            ft.Icons.LOOKS_ONE,
            "module.first",
            "FirstView",
        ),
        FeatureDescriptor(
            "second",
            "sidebar.second",
            "第二个",
            ft.Icons.LOOKS_TWO,
            "module.second",
            "SecondView",
        ),
    ))

    tabs = registry.sidebar_definitions(lambda _key, default: default)
    catalog = registry.create_view_catalog()

    assert [tab["id"] for tab in tabs] == ["first", "second"]
    assert catalog.view_ids == ("first", "second")


def test_feature_descriptor_explicit_factories_are_authoritative() -> None:
    context = object()
    view = object()
    feature = FeatureDescriptor(
        "factory",
        "sidebar.factory",
        "Factory",
        ft.Icons.BUILD,
        view_factory=lambda received: view if received is context else None,
        top_actions_factory=lambda current_view: (
            "action" if current_view is view else "wrong",
        ),
    )
    registry = FeatureRegistry((feature,))

    catalog = registry.create_view_catalog()
    created = catalog.create("factory", context)

    assert created is view
    assert catalog.get_top_actions("factory", created) == ("action",)


def test_feature_descriptor_accepts_factory_position_arguments() -> None:
    context = object()
    view = object()
    feature = FeatureDescriptor(
        "positional",
        "sidebar.positional",
        "Positional",
        ft.Icons.BUILD,
        lambda received: view if received is context else None,
        lambda current_view: ("action",) if current_view is view else (),
    )

    catalog = FeatureRegistry((feature,)).create_view_catalog()

    created = catalog.create("positional", context)
    assert created is view
    assert catalog.get_top_actions("positional", created) == ("action",)


def test_default_feature_registry_matches_default_view_catalog() -> None:
    assert tuple(
        feature.view_id for feature in DEFAULT_FEATURE_REGISTRY.features
    ) == create_default_view_catalog().view_ids


def test_default_features_declare_capabilities_without_changing_defaults() -> None:
    assert DEFAULT_FEATURE_REGISTRY.capabilities
    assert all(
        feature.required_capabilities
        for feature in DEFAULT_FEATURE_REGISTRY.features
    )
    assert create_default_view_catalog().view_ids == tuple(
        feature.view_id for feature in DEFAULT_FEATURE_REGISTRY.features
    )
    assert all(
        feature.view_factory is not None
        and feature.top_actions_factory is not None
        for feature in DEFAULT_FEATURE_REGISTRY.features
    )
