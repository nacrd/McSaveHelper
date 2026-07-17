from app.ui.views.explorer.map.map_hit_testing import hit_bounds, rect_contains


def test_hit_bounds_prefers_allowed_coords() -> None:
    bounds = {
        (0, 0): (0.0, 0.0, 10.0, 10.0),
        (1, 0): (10.0, 0.0, 10.0, 10.0),
    }

    assert hit_bounds(5, 5, bounds, allowed={(1, 0)}) is None
    assert hit_bounds(15, 5, bounds, allowed={(1, 0)}) == (1, 0)
    assert rect_contains(15, 5, bounds[(1, 0)]) is True
