from app.ui.components.floating_position import (
    DragTracker,
    FloatingBounds,
    clamp_position,
)


def test_clamp_position_keeps_control_inside_viewport() -> None:
    bounds = FloatingBounds(100, 80, 30, 20)

    assert clamp_position(-10, 100, bounds) == (0.0, 60)
    assert clamp_position(25, 35, bounds) == (25, 35)


def test_drag_tracker_returns_incremental_deltas() -> None:
    tracker = DragTracker()

    assert tracker.update(2, 3) is None
    tracker.start(10, 20)
    assert tracker.update(13, 18) == (3, -2)
    assert tracker.update(15, 21) == (2, 3)
    tracker.end()
    assert tracker.update(20, 20) is None
