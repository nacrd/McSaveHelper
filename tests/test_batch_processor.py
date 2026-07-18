import threading
from pathlib import Path

import pytest

from core.batch_processor import BatchCancelledError, BatchProcessor


def _world(parent: Path, name: str) -> Path:
    world = parent / name
    world.mkdir(parents=True)
    (world / "level.dat").write_bytes(b"level")
    return world


def test_batch_rejects_mismatched_or_duplicate_target_names(tmp_path: Path) -> None:
    worlds = [_world(tmp_path, "a"), _world(tmp_path, "b")]
    processor = BatchProcessor()

    with pytest.raises(ValueError, match="数量必须完全一致"):
        processor.process_batch(worlds, tmp_path / "out", ["only-one"])
    with pytest.raises(ValueError, match="不能重复"):
        processor.process_batch(worlds, tmp_path / "out", ["same", "same"])


def test_batch_uses_stable_task_ids_for_same_named_sources(tmp_path: Path) -> None:
    first = _world(tmp_path / "one", "world")
    second = _world(tmp_path / "two", "world")

    def handler(source, destination, world_name, log, cancel_event):
        del destination, log, cancel_event
        return {
            "success": True,
            "marker": str(source),
            "output_path": str(tmp_path / world_name),
        }

    processor = BatchProcessor(max_workers=2, task_handler=handler)

    results = processor.process_batch(
        [first, second],
        tmp_path / "out",
        ["target-a", "target-b"],
    )

    assert set(results) == {"task-1", "task-2"}
    assert {result["source_path"] for result in results.values()} == {
        str(first.resolve()),
        str(second.resolve()),
    }


def test_different_batch_tasks_run_concurrently(tmp_path: Path) -> None:
    worlds = [_world(tmp_path, "a"), _world(tmp_path, "b")]
    barrier = threading.Barrier(2)

    def handler(source, destination, world_name, log, cancel_event):
        del source, destination, world_name, log, cancel_event
        barrier.wait(timeout=2)
        return {"success": True}

    processor = BatchProcessor(max_workers=2, task_handler=handler)

    results = processor.process_batch(worlds, tmp_path / "out")

    assert all(result["success"] for result in results.values())


def test_stop_cancels_pending_tasks_and_preserves_running_state(tmp_path: Path) -> None:
    worlds = [_world(tmp_path, "a"), _world(tmp_path, "b")]
    started = threading.Event()
    release = threading.Event()

    def handler(source, destination, world_name, log, cancel_event):
        del source, destination, world_name, log
        started.set()
        cancel_event.wait(timeout=2)
        release.wait(timeout=2)
        raise BatchCancelledError("cancelled at checkpoint")

    processor = BatchProcessor(max_workers=1, task_handler=handler)
    returned = []
    thread = threading.Thread(
        target=lambda: returned.append(
            processor.process_batch(worlds, tmp_path / "out")
        )
    )
    thread.start()
    assert started.wait(timeout=2)

    processor.stop()

    assert processor.is_running is True
    release.set()
    thread.join(timeout=3)
    assert not thread.is_alive()
    assert processor.is_running is False
    assert len(returned[0]) == 2
    assert all(result.get("cancelled") for result in returned[0].values())
