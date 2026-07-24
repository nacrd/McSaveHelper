from pathlib import Path

from app.presenters.compare_view_state import (
    ComparePhase,
    begin_compare,
    complete_compare,
    fail_compare,
    initial_compare_state,
    invalidate_compare,
)
from app.services.world_compare_service import CompareItem, WorldCompareResult


def _result() -> WorldCompareResult:
    return WorldCompareResult(
        summary={"changed": 2, "world_info": 1, "players": 1, "regions": 1},
        world_info=[CompareItem("seed", "1", "2", same=False)],
        players=[CompareItem("Alex", "same", "same", same=True)],
        regions=[CompareItem("r.0.0.mca", "old", "new", same=False)],
    )


def test_compare_state_projects_only_changed_items() -> None:
    running = begin_compare(
        initial_compare_state(),
        Path("left"),
        Path("right"),
    )

    completed = complete_compare(running, _result(), running.generation)

    assert completed.phase is ComparePhase.COMPLETE
    assert completed.summary == "变更项: 2 / 3"
    assert completed.left_path == Path("left")
    assert [len(group.items) for group in completed.groups] == [1, 0, 1]


def test_compare_state_rejects_stale_result_and_error() -> None:
    first = begin_compare(initial_compare_state(), Path("a"), Path("b"))
    current = begin_compare(first, Path("c"), Path("d"))

    assert complete_compare(current, _result(), first.generation) is current
    assert fail_compare(current, first.generation) is current


def test_compare_state_failure_and_dispose_end_busy_phase() -> None:
    running = begin_compare(initial_compare_state(), Path("a"), Path("b"))

    failed = fail_compare(running, running.generation)
    disposed = invalidate_compare(running)

    assert failed.phase is ComparePhase.ERROR
    assert failed.is_comparing is False
    assert disposed.phase is ComparePhase.IDLE
    assert disposed.generation == running.generation + 1
