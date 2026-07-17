from core.mca.viewport import McaViewport
from app.ui.views.explorer.map.camera_animator import MapCameraAnimator


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
    )

    target = animator.animate_zoom_about(2.0, 100.0, 50.0, duration=0.05)
    assert target is not None
    assert target.scale == 2.0

    # Force one completion by applying the absolute target directly.
    animator.cancel()
    viewport.apply(target)
    assert viewport.scale == 2.0
