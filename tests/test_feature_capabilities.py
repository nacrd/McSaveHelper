"""FeatureDescriptor capability gating."""
from __future__ import annotations

from app.ui.feature_registry import FeatureDescriptor
from app.ui.icons import IconSet


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
