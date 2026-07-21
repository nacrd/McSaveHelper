"""Regression tests for the Explorer player-list presentation."""
from typing import Callable

import flet as ft

from app.services.player.models import PlayerRef
from app.ui.views.explorer.player_tab import PlayerTabMixin


def _translate(key: str, default: str = "", **kwargs: object) -> str:
    del key, kwargs
    return default


class _PlayerTabHarness(PlayerTabMixin):
    @property
    def _t(self) -> Callable[..., str]:
        return _translate


def test_player_filter_does_not_expand_vertically_and_push_list_down() -> None:
    view = _PlayerTabHarness()

    left = view._build_player_left_column(_translate)

    assert view._player_filter.expand is False
    assert isinstance(left.controls[-1], ft.Container)
    assert left.controls[-1].expand is True


def test_unnamed_player_tile_does_not_repeat_uuid_as_name() -> None:
    view = _PlayerTabHarness()
    view.current_uuid = None
    view._player_col_widths = [280.0]
    player = PlayerRef(
        uuid_norm="05dd73a32fc4470a8f8ea43a2a4038c4",
        uuid_hyphen="05dd73a3-2fc4-470a-8f8e-a43a2a4038c4",
        name=None,
    )

    tile = view._build_player_list_tile(player)

    assert isinstance(tile.content, ft.Row)
    avatar = tile.content.controls[0]
    assert isinstance(avatar, ft.CircleAvatar)
    assert isinstance(avatar.content, ft.Icon)
    labels = tile.content.controls[1]
    assert isinstance(labels, ft.Column)
    assert isinstance(labels.controls[0], ft.Text)
    assert labels.controls[0].value == "未知玩家"
