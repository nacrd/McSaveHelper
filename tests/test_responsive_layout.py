"""Responsive shell breakpoint contracts."""
import pytest

from app.models.responsive_layout import resolve_responsive_layout


@pytest.mark.parametrize(
    ("width", "density", "collapsed", "padding"),
    [
        (800, "narrow", True, 10),
        (900, "compact", True, 14),
        (1100, "standard", False, 20),
        (1400, "roomy", False, 28),
    ],
)
def test_responsive_layout_resolves_stable_width_bands(
    width: float,
    density: str,
    collapsed: bool,
    padding: int,
) -> None:
    layout = resolve_responsive_layout(width, 820)

    assert layout.density == density
    assert layout.sidebar_collapsed is collapsed
    assert layout.content_padding == padding


def test_narrow_layout_prioritizes_commands() -> None:
    layout = resolve_responsive_layout(800, 600)

    assert layout.action_width_limit == 140
    assert layout.visible_action_count == 2
    assert layout.action_height == 44


def test_short_wide_window_reduces_vertical_density_only() -> None:
    layout = resolve_responsive_layout(1400, 650)

    assert layout.density == "roomy"
    assert layout.sidebar_collapsed is False
    assert layout.sidebar_width == 240
    assert layout.is_compact is True
    assert layout.content_padding == 14


def test_expanded_sidebar_stays_compact_across_desktop_widths() -> None:
    assert resolve_responsive_layout(1100, 820).sidebar_width == 224
    assert resolve_responsive_layout(1400, 820).sidebar_width == 240
