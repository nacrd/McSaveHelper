"""FeatureDescriptor capability gating."""
from __future__ import annotations

import pytest

from app.ui.application_shell import build_tab_definitions
from app.ui.feature_registry import FeatureDescriptor, FeatureRegistry
from app.ui.icons import IconSet
from app.ui.view_catalog import create_default_view_catalog


def test_required_capabilities_subset_check() -> None:
    feature = FeatureDescriptor(
        "demo",
        "sidebar.demo",
        "Demo",
        IconSet.MAP,
        "app.ui.views.demo",
        "DemoView",
        required_capabilities=frozenset({"world.read", "map.tiles"}),
    )
    assert feature.has_capabilities(
        frozenset({"world.read", "map.tiles", "extra"})
    )
    assert not feature.has_capabilities(frozenset({"world.read"}))


def test_capabilities_filter_navigation_and_view_creation_together() -> None:
    allowed = FeatureDescriptor(
        "allowed",
        "sidebar.allowed",
        "Allowed",
        IconSet.MAP,
        "app.ui.views.allowed",
        "AllowedView",
        required_capabilities=frozenset({"world.read"}),
    )
    blocked = FeatureDescriptor(
        "blocked",
        "sidebar.blocked",
        "Blocked",
        IconSet.BUILD,
        "app.ui.views.blocked",
        "BlockedView",
        required_capabilities=frozenset({"world.write"}),
    )
    registry = FeatureRegistry((allowed, blocked))
    available = frozenset({"world.read"})

    tabs = registry.sidebar_definitions(
        lambda _key, default: default,
        available,
    )
    catalog = registry.create_view_catalog(
        available_capabilities=available,
    )

    assert [tab["id"] for tab in tabs] == ["allowed"]
    assert catalog.view_ids == ("allowed",)
    with pytest.raises(KeyError, match="未注册的视图"):
        catalog.create("blocked", object())


def test_default_runtime_entry_points_share_capability_filter() -> None:
    available = frozenset({"app.settings"})

    tabs = build_tab_definitions(
        lambda _key, default: default,
        available_capabilities=available,
    )
    catalog = create_default_view_catalog(
        available_capabilities=available,
    )

    assert [tab["id"] for tab in tabs] == ["settings"]
    assert catalog.view_ids == ("settings",)
    with pytest.raises(KeyError, match="未注册的视图"):
        catalog.create("explorer", object())
