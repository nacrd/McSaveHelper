"""Extreme-window layouts keep every information panel reachable."""
from types import SimpleNamespace
from typing import cast

import flet as ft

from app.ui.views.entity_block_search import EntityBlockSearchView
from app.ui.views.explorer.nbt_tab import NbtTabMixin
from app.ui.views.explorer.player_tab import PlayerTabMixin
from app.ui.views.migrator import MigratorView


def _panel(width: int) -> ft.Container:
    return ft.Container(content=ft.Text(str(width)), width=width)


def test_compact_player_layout_stacks_all_three_panels() -> None:
    view = PlayerTabMixin()
    view._player_left_panel = _panel(280)
    view._player_center_panel = _panel(340)
    view._player_right_panel = _panel(520)
    view._player_split_left = ft.Container()
    view._player_split_right = ft.Container()
    view._player_layout = ft.Row()
    view._player_layout_host = ft.Container()
    view._player_col_widths = [280.0, 340.0, 520.0]

    view._set_player_compact_layout(True)

    stacked = view._player_layout_host.content
    assert isinstance(stacked, ft.Column)
    assert stacked.scroll == ft.ScrollMode.AUTO
    assert stacked.controls == [
        view._player_left_panel,
        view._player_center_panel,
        view._player_right_panel,
    ]
    for panel in stacked.controls:
        assert isinstance(panel, ft.Container)
        assert panel.width is None


def test_compact_nbt_layout_stacks_navigation_tree_and_stage_panels() -> None:
    view = NbtTabMixin()
    view._nbt_root = ft.Container()
    view._nbt_left_panel = _panel(280)
    view._nbt_center_panel = _panel(520)
    view._nbt_right_panel = _panel(300)

    view._set_nbt_compact_layout(True)

    stacked = view._nbt_root.content
    assert isinstance(stacked, ft.Column)
    assert stacked.scroll == ft.ScrollMode.AUTO
    assert len(stacked.controls) == 3
    assert view._nbt_center_panel.height == 420


def test_compact_search_layout_keeps_all_three_panels() -> None:
    panels = (_panel(280), _panel(400), _panel(280))
    view = cast(
        EntityBlockSearchView,
        SimpleNamespace(
            _layout_host=ft.Container(),
            _layout_panels=panels,
        ),
    )

    EntityBlockSearchView.set_compact_mode(view, True)

    stacked = view._layout_host.content
    assert isinstance(stacked, ft.Column)
    assert stacked.controls == list(panels)
    assert panels[1].height == 360


def test_compact_migrator_layout_keeps_both_card_columns() -> None:
    left = ft.Column()
    right = ft.Column()
    view = cast(
        MigratorView,
        SimpleNamespace(
            _content_host=ft.Container(),
            _left_content=left,
            _right_content=right,
            _content_gap=ft.Container(width=24),
        ),
    )

    MigratorView.set_compact_mode(view, True)

    stacked = view._content_host.content
    assert isinstance(stacked, ft.Column)
    assert stacked.controls == [left, right]
