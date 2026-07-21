"""Viewport-based layout policy shared by the application shell."""
from dataclasses import dataclass
from typing import Literal


LayoutDensity = Literal["narrow", "compact", "standard", "roomy"]


@dataclass(frozen=True)
class ResponsiveLayout:
    """Resolved shell dimensions for one viewport snapshot.

    Attributes:
        density: Stable width band used by shell and view adapters.
        is_compact: Whether page internals should use their compact layout.
        sidebar_collapsed: Whether navigation is shown as an icon rail.
        sidebar_width: Expanded navigation width in pixels.
        content_padding: Content canvas inset in pixels.
        action_height: Top command button height in pixels.
        action_width_limit: Maximum top command width in pixels.
        visible_action_count: Number of direct commands before overflow.
        action_spacing: Gap between top commands in pixels.
    """

    density: LayoutDensity
    is_compact: bool
    sidebar_collapsed: bool
    sidebar_width: int
    content_padding: int
    action_height: int
    action_width_limit: int
    visible_action_count: int | None
    action_spacing: int


def resolve_responsive_layout(
    width: float,
    height: float,
) -> ResponsiveLayout:
    """Resolve deterministic shell settings for a window viewport.

    Args:
        width: Current logical viewport width.
        height: Current logical viewport height.

    Returns:
        Immutable layout settings for the matching breakpoint.
    """
    density = _resolve_density(width)
    is_short = height < 700
    layouts: dict[LayoutDensity, ResponsiveLayout] = {
        "narrow": ResponsiveLayout(
            density="narrow",
            is_compact=True,
            sidebar_collapsed=True,
            sidebar_width=248,
            content_padding=10,
            action_height=44,
            action_width_limit=140,
            visible_action_count=2,
            action_spacing=4,
        ),
        "compact": ResponsiveLayout(
            density="compact",
            is_compact=True,
            sidebar_collapsed=True,
            sidebar_width=248,
            content_padding=14,
            action_height=44,
            action_width_limit=140,
            visible_action_count=3,
            action_spacing=5,
        ),
        "standard": ResponsiveLayout(
            density="standard",
            is_compact=is_short,
            sidebar_collapsed=False,
            sidebar_width=248,
            content_padding=20 if not is_short else 12,
            action_height=44,
            action_width_limit=120 if is_short else 140,
            visible_action_count=5,
            action_spacing=6,
        ),
        "roomy": ResponsiveLayout(
            density="roomy",
            is_compact=is_short,
            sidebar_collapsed=False,
            sidebar_width=280,
            content_padding=28 if not is_short else 14,
            action_height=44,
            action_width_limit=120 if is_short else 140,
            visible_action_count=None,
            action_spacing=8,
        ),
    }
    return layouts[density]


def _resolve_density(width: float) -> LayoutDensity:
    if width < 900:
        return "narrow"
    if width < 1100:
        return "compact"
    if width < 1400:
        return "standard"
    return "roomy"
