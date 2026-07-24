"""应用级统一操作指标存储测试。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from app.services.operation_metrics import OperationMetricsStore
from core.observability import OperationOutcome, OperationRecord
from core.performance import PerformanceMetrics


def _record(index: int, *, feature: str = "map") -> OperationRecord:
    return OperationRecord(
        operation_id=f"task-{index}",
        feature=feature,
        world_id="world-a",
        outcome=(
            OperationOutcome.ERROR
            if index % 2
            else OperationOutcome.OK
        ),
        metadata={"index": index},
    )


def test_store_is_bounded_and_keeps_newest_records() -> None:
    store = OperationMetricsStore(max_records=2)
    store.record(_record(1))
    store.record(_record(2))
    store.record(_record(3))

    assert [item.operation_id for item in store.snapshot()] == [
        "task-2",
        "task-3",
    ]
    assert store.record_count == 2


def test_record_metrics_assigns_unique_id_and_preserves_stable_operation() -> None:
    store = OperationMetricsStore()
    metrics = PerformanceMetrics(
        operation="scan_world",
        duration_seconds=0.02,
        memory_peak_mb=0.0,
        memory_delta_mb=0.0,
    )

    first = store.record_metrics(metrics, feature="stats")
    second = store.record_metrics(metrics, feature="stats")

    assert first.operation_id != second.operation_id
    assert first.metadata["operation"] == "scan_world"
    assert store.snapshot(feature="stats") == (first, second)


def test_snapshot_filters_by_dimensions_and_limit() -> None:
    store = OperationMetricsStore()
    store.record(_record(0))
    store.record(_record(1))
    store.record(_record(2, feature="stats"))

    assert len(store.snapshot(world_id="world-a", outcome=OperationOutcome.OK)) == 2
    assert [item.operation_id for item in store.snapshot(feature="map", limit=1)] == [
        "task-1",
    ]


def test_store_snapshots_metadata_without_aliasing() -> None:
    store = OperationMetricsStore()
    metadata = {"mutable": "before"}
    record = OperationRecord("task", "map", metadata=metadata)
    store.record(record)
    metadata["mutable"] = "after"

    stored = store.snapshot()[0]
    assert stored.metadata["mutable"] == "before"


def test_store_accepts_concurrent_publishers() -> None:
    store = OperationMetricsStore(max_records=64)
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda index: store.record(_record(index)), range(32)))

    assert store.record_count == 32
    assert len({item.operation_id for item in store.snapshot()}) == 32
