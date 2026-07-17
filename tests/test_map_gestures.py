from core.mca.map_gestures import (
    decide_double_tap,
    decide_secondary_tap,
    decide_tap,
)
from core.mca.map_navigation import McaMapNavigator


def test_decide_tap_selects_region_and_focuses() -> None:
    navigator = McaMapNavigator()
    result = decide_tap(
        navigator=navigator,
        region_sizes={(1, 2): 10},
        view_level="world",
        scale=1.0,
        scale_block=20.0,
        hit_chunk=None,
        hit_region=(1, 2),
    )

    assert result is not None
    assert result.focus_region == (1, 2)
    assert result.set_level == "region"
    assert result.notification is not None
    assert result.notification.region == (1, 2)


def test_decide_double_tap_dives_into_chunk() -> None:
    navigator = McaMapNavigator()
    result = decide_double_tap(
        navigator=navigator,
        region_sizes={(1, 0): 8},
        view_level="chunk",
        hit_chunk=(33, 4),
        hit_region=(1, 0),
        selected_region=(1, 0),
    )

    assert result is not None
    assert result.focus_chunk == (33, 4)
    assert result.set_level == "block"


def test_decide_secondary_tap_steps_back_to_overview() -> None:
    navigator = McaMapNavigator()
    navigator.select_region((0, 0), {(0, 0): 1}, "region")
    result = decide_secondary_tap(
        navigator=navigator,
        region_sizes={(0, 0): 1},
        previous_level="region",
        selected_region=(0, 0),
    )

    assert result.fit_to_view is True
    assert result.notification is not None
    assert result.notification.detail["level"] == "world"
