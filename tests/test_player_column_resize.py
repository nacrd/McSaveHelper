"""Unit tests for player-tab column resize helpers."""
from app.ui.views.explorer.player_tab import (
    normalize_column_widths,
    resize_adjacent_columns,
)


def test_resize_adjacent_columns_moves_width() -> None:
    result = resize_adjacent_columns(
        [200.0, 300.0, 400.0],
        [100.0, 100.0, 100.0],
        boundary=0,
        delta=50.0,
    )
    assert result == [250.0, 250.0, 400.0]


def test_resize_adjacent_columns_respects_minimums() -> None:
    result = resize_adjacent_columns(
        [200.0, 300.0, 400.0],
        [190.0, 290.0, 100.0],
        boundary=0,
        delta=-50.0,
    )
    assert result[0] == 190.0
    assert result[1] == 310.0
    assert result[2] == 400.0


def test_resize_adjacent_columns_rejects_impossible_boundary() -> None:
    original = [200.0, 300.0, 400.0]
    assert resize_adjacent_columns(original, [100.0, 100.0, 100.0], 5, 10.0) == original
    assert resize_adjacent_columns(original, [100.0, 100.0, 100.0], -1, 10.0) == original


def test_normalize_column_widths_scales_to_available() -> None:
    result = normalize_column_widths(
        [200.0, 300.0, 400.0],
        [100.0, 100.0, 100.0],
        available=1200.0,
    )
    assert abs(sum(result) - 1200.0) < 0.01
    assert all(result[i] >= 100.0 for i in range(3))


def test_normalize_column_widths_keeps_floor_when_too_small() -> None:
    result = normalize_column_widths(
        [200.0, 300.0, 400.0],
        [160.0, 260.0, 280.0],
        available=100.0,
    )
    assert abs(sum(result) - (160.0 + 260.0 + 280.0)) < 0.01
