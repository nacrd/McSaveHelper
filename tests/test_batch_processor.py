import threading
from pathlib import Path
from typing import Callable, Optional, Sequence, TypeVar

import pytest

from core.types import BatchResult

from app.services.execution_runtime import ExecutionRuntime, LaneLimits
from app.services.parallel_runner import RuntimeParallelRunner
from core.batch_processor import BatchCancelledError, BatchProcessor


ItemT = TypeVar("ItemT")
ResultT = TypeVar("ResultT")


class _DuplicateCallbackRunner:
    """测试替身：每项重复通知完成，同时仍返回完整结果。"""

    def map(
        self,
        operation: str,
        items: Sequence[ItemT],
        worker: Callable[[ItemT], ResultT],
        *,
        max_workers: Optional[int] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        on_item_done: Optional[
            Callable[[int, ResultT | BaseException], None]
        ] = None,
    ) -> list[ResultT | BaseException]:
        del operation, max_workers, cancel_check
        results: list[ResultT | BaseException] = []
        for index, item in enumerate(items):
            value: ResultT | BaseException = worker(item)
            results.append(value)
            if on_item_done is not None:
                on_item_done(index, value)
                on_item_done(index, value)
        return results


class _ShortResultRunner:
    """测试替身：违反等长返回契约。"""

    def map(
        self,
        operation: str,
        items: Sequence[ItemT],
        worker: Callable[[ItemT], ResultT],
        *,
        max_workers: Optional[int] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        on_item_done: Optional[
            Callable[[int, ResultT | BaseException], None]
        ] = None,
    ) -> list[ResultT | BaseException]:
        del operation, items, worker, max_workers, cancel_check, on_item_done
        return []


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
    runtime = ExecutionRuntime(
        io_limits=LaneLimits(1, 1),
        cpu_limits=LaneLimits(2, 2),
    )

    def handler(source, destination, world_name, log, cancel_event):
        del source, destination, world_name, log, cancel_event
        barrier.wait(timeout=2)
        return {"success": True}

    processor = BatchProcessor(
        max_workers=2,
        task_handler=handler,
        runner=RuntimeParallelRunner(runtime),
    )

    try:
        results = processor.process_batch(worlds, tmp_path / "out")
        assert all(result["success"] for result in results.values())
    finally:
        runtime.shutdown(wait=True)


def test_duplicate_completion_notifications_are_accounted_once(
    tmp_path: Path,
) -> None:
    worlds = [_world(tmp_path, "a"), _world(tmp_path, "b")]
    progress: list[float] = []
    processor = BatchProcessor(
        task_handler=lambda *args: {"success": True},
        runner=_DuplicateCallbackRunner(),
    )

    results = processor.process_batch(
        worlds,
        tmp_path / "out",
        progress_callback=progress.append,
    )

    assert len(results) == 2
    assert progress == [0.5, 1.0]


def test_parallel_runner_must_return_one_result_per_task(tmp_path: Path) -> None:
    worlds = [_world(tmp_path, "a")]
    processor = BatchProcessor(
        task_handler=lambda *args: {"success": True},
        runner=_ShortResultRunner(),
    )

    with pytest.raises(RuntimeError, match="结果数量"):
        processor.process_batch(worlds, tmp_path / "out")

    assert processor.is_running is False


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
    progress: list[float] = []
    thread = threading.Thread(
        target=lambda: returned.append(
            processor.process_batch(
                worlds,
                tmp_path / "out",
                progress_callback=progress.append,
            )
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
    assert progress == [0.5, 1.0]


@pytest.mark.parametrize(
    ("mode", "target"),
    (
        ("fast", "core.fast_mode.run_fast"),
        ("full", "core.full_mode.run_full"),
    ),
)
def test_default_handler_forwards_cancel_and_classifies_runtime_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    target: str,
) -> None:
    world = _world(tmp_path, "world")
    started = threading.Event()
    release = threading.Event()
    observed_cancel: list[bool] = []

    def fake_run_mode(*args, **kwargs) -> None:
        del args
        cancel_check = kwargs["cancel_check"]
        started.set()
        release.wait(timeout=2)
        observed_cancel.append(bool(cancel_check()))
        raise RuntimeError("copy cancelled")

    monkeypatch.setattr(target, fake_run_mode)
    processor = BatchProcessor(max_workers=1)
    returned: list[BatchResult] = []
    thread = threading.Thread(
        target=lambda: returned.append(
            processor.process_batch(
                [world],
                tmp_path / "out",
                mode=mode,
            )
        )
    )
    thread.start()
    try:
        assert started.wait(timeout=2)
        processor.stop()
        release.set()
        thread.join(timeout=2)
        assert not thread.is_alive()
    finally:
        release.set()
        thread.join(timeout=2)

    result = next(iter(returned[0].values()))
    assert observed_cancel == [True]
    assert result["cancelled"] is True
    assert result["success"] is False
