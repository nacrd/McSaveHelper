"""Shared UI design-system contracts."""
import flet as ft

from app.ui.components.cards import card
from app.ui.components.fields import text_field
from app.ui.components.layout import TabSpec, panel, segmented_tab_bar
from app.ui.icons import IconSet
from app.ui.theme import DARK_THEME, LIGHT_THEME, THEME, mc_border


def _relative_luminance(color: str) -> float:
    channels = [
        int(color[index:index + 2], 16) / 255
        for index in (1, 3, 5)
    ]
    linear = [
        channel / 12.92
        if channel <= 0.04045
        else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return sum(
        channel * weight
        for channel, weight in zip(linear, (0.2126, 0.7152, 0.0722))
    )


def _contrast(first: str, second: str) -> float:
    light, dark = sorted(
        (_relative_luminance(first), _relative_luminance(second)),
        reverse=True,
    )
    return (light + 0.05) / (dark + 0.05)


def test_workspace_surfaces_use_uniform_thin_borders() -> None:
    border = mc_border(1)
    content_panel = panel(ft.Text("content"))
    content_card = card(ft.Text("content"))

    assert border.left.color == DARK_THEME.border_standard
    assert border.left.width == 1
    assert border.left == border.right == border.top == border.bottom
    assert content_panel.border_radius == 6
    assert content_card.border_radius == 6


def test_segmented_tabs_are_compact_horizontal_controls() -> None:
    bar, row, buttons, labels = segmented_tab_bar(
        [TabSpec("存档", IconSet.SAVE), TabSpec("设置", IconSet.SETTINGS)],
        selected_index=0,
        on_select=lambda index: None,
    )

    assert bar.border_radius == 6
    assert row.scroll == ft.ScrollMode.AUTO
    assert buttons[0].height == 44
    assert isinstance(buttons[0].content, ft.Row)
    assert labels[0].color == THEME.text_primary


def test_text_fields_use_card_surface_and_focus_ring() -> None:
    field = text_field(label="名称")

    assert field.bgcolor == THEME.bg_card
    assert field.focused_border_color == THEME.focus_ring


def test_helper_text_and_control_boundaries_meet_contrast_targets() -> None:
    assert _contrast(LIGHT_THEME.text_muted, LIGHT_THEME.bg_secondary) >= 4.5
    assert _contrast(LIGHT_THEME.border_standard, LIGHT_THEME.bg_card) >= 3
    assert _contrast(DARK_THEME.border_standard, DARK_THEME.bg_card) >= 3


def test_brand_accent_and_success_have_distinct_semantics() -> None:
    assert LIGHT_THEME.accent != LIGHT_THEME.success
    assert DARK_THEME.accent != DARK_THEME.success
