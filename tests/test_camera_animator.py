import pytest

from app.ui.views.explorer.map.camera_animator import MapCameraAnimator
from core.mca.viewport import McaViewport


class _Call:
    def __init__(self, callback):
        self.callback = callback
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def fire(self, *, force=False):
        if force or not self.cancelled:
            self.callback()


class _Scheduler:
    def __init__(self):
        self.calls = []

    def __call__(self, delay, callback):
        call = _Call(callback)
        self.calls.append((delay, call))
        return call


class _FailingScheduler:
    def __call__(self, _delay, _callback):
        raise RuntimeError("scheduler failed")


def test_camera_animator_zoom_about_updates_viewport_target() -> None:
    viewport = McaViewport(scale=1.0, offset_x=0.0, offset_y=0.0)
    frames = []
    completes = []

    animator = MapCameraAnimator(
        viewport,
        min_scale=0.1,
        max_scale=320.0,
        on_frame=lambda: frames.append(viewport.current_target),
        on_complete=lambda: completes.append(viewport.current_target),
        is_alive=lambda: True,
        schedule=_Scheduler(),
    )

    target = animator.animate_zoom_about(2.0, 100.0, 50.0, duration=0.05)
    assert target is not None
    assert target.scale == 2.0

    # Force one completion by applying the absolute target directly.
    animator.cancel()
    viewport.apply(target)
    assert viewport.scale == 2.0


def test_camera_animator_ignores_late_callback_from_previous_generation(
    monkeypatch,
) -> None:
    now = [0.0]
    monkeypatch.setattr(
        "app.ui.views.explorer.map.camera_animator.time.monotonic",
        lambda: now[0],
    )
    viewport = McaViewport(scale=1.0, offset_x=0.0, offset_y=0.0)
    scheduler = _Scheduler()
    animator = MapCameraAnimator(
        viewport,
        min_scale=0.1,
        max_scale=320.0,
        on_frame=lambda: None,
        on_complete=lambda: None,
        is_alive=lambda: True,
        schedule=scheduler,
    )

    animator.animate_to(2.0, 10.0, 20.0, duration=0.05)
    old_call = scheduler.calls[-1][1]
    animator.animate_to(3.0, 30.0, 40.0, duration=0.05)
    old_call.fire(force=True)

    assert viewport.current_target.scale == 1.0
    assert animator.target.scale == 3.0


@pytest.mark.parametrize(
    "schedule, raises",
    [
        (lambda _delay, _callback: None, False),
        (_FailingScheduler(), True),
    ],
)
def test_camera_animator_recovers_when_scheduler_is_unavailable(
    schedule,
    raises,
) -> None:
    animator = MapCameraAnimator(
        McaViewport(),
        min_scale=0.1,
        max_scale=320.0,
        on_frame=lambda: None,
        on_complete=lambda: None,
        is_alive=lambda: True,
        schedule=schedule,
    )

    if raises:
        with pytest.raises(RuntimeError, match="scheduler failed"):
            animator.animate_to(2.0, 0.0, 0.0)
    else:
        animator.animate_to(2.0, 0.0, 0.0)

    assert animator.active is False
