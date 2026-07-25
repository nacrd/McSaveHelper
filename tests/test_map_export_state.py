"""Map export immutable lifecycle-state tests."""
from app.presenters.map_export_state import (
    MapExportState,
    begin_map_export,
    dispose_map_export,
    finish_map_export,
    owns_map_export,
    request_map_export_cancel,
)


def test_map_export_state_owns_only_latest_running_generation() -> None:
    initial = MapExportState()
    running = begin_map_export(initial)

    assert owns_map_export(running, running.generation) is True
    assert begin_map_export(running) is running

    cancelling = request_map_export_cancel(running)
    assert cancelling.cancel_requested is True
    assert owns_map_export(cancelling, cancelling.generation) is True

    finished = finish_map_export(cancelling, cancelling.generation)
    assert finished.is_running is False
    assert owns_map_export(finished, finished.generation) is False


def test_disposed_map_export_state_rejects_new_and_stale_requests() -> None:
    running = begin_map_export(MapExportState())
    disposed = dispose_map_export(running)

    assert disposed.is_disposed is True
    assert disposed.is_running is False
    assert owns_map_export(disposed, running.generation) is False
    assert begin_map_export(disposed) is disposed
