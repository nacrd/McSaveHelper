"""Region delete use case runs only on the shared runtime I/O lane."""
from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, cast

import pytest

from app.controllers.region_delete_controller import (
    RegionDeleteBusyError,
    RegionDeleteController,
    RegionDeleteOutcome,
    RegionDeleteRequest,
    RegionDeleteStatus,
)
from app.services.backup_service import BackupRecord
from app.services.execution_runtime import ExecutionRuntime
from app.services.world_transaction import (
    WorldTransactionCancelledError,
    WorldTransactionResult,
    WorldTransactionService,
)


class _BlockingTransactions:
    """Expose cancellation and thread identity without touching disk."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.worker_name = ""

    def mutate(
        self,
        world_path: Path | str,
        mutation: Callable[[Path], bool],
        *,
        backup_label: str,
        cancel_check: Callable[[], bool] | None = None,
        validator: object = None,
    ) -> WorldTransactionResult[bool]:
        del mutation, backup_label, validator
        self.worker_name = threading.current_thread().name
        self.started.set()
        if not self.release.wait(1):
            raise AssertionError("test did not release region deletion")
        if cancel_check is not None and cancel_check():
            raise WorldTransactionCancelledError("cancelled")
        backup = cast(
            BackupRecord,
            SimpleNamespace(backup_path=Path("backup")),
        )
        return WorldTransactionResult(
            value=True,
            world_path=Path(world_path),
            backup=backup,
        )


def _request(tmp_path: Path) -> RegionDeleteRequest:
    world = tmp_path / "world"
    return RegionDeleteRequest(
        world_path=world,
        region_path=world / "region" / "r.0.0.mca",
        coord=(0, 0),
        generation=1,
    )


def test_start_returns_while_delete_runs_on_io_worker(tmp_path: Path) -> None:
    runtime = ExecutionRuntime()
    transactions = _BlockingTransactions()
    controller = RegionDeleteController(
        runtime.create_scope("region_delete_test"),
        cast(WorldTransactionService, transactions),
    )
    completed = threading.Event()
    outcomes: list[RegionDeleteOutcome] = []

    def on_complete(outcome: RegionDeleteOutcome) -> None:
        outcomes.append(outcome)
        completed.set()

    try:
        handle = controller.start(
            _request(tmp_path),
            on_complete,
        )
        assert transactions.started.wait(1)
        assert not handle.done
        assert not completed.is_set()
        assert transactions.worker_name.startswith("mcsavehelper-io-")

        transactions.release.set()
        assert handle.result(timeout=1).value is True
        assert completed.wait(1)
        assert outcomes[0].status is RegionDeleteStatus.SUCCEEDED
    finally:
        transactions.release.set()
        runtime.shutdown(wait=True)


def test_cancel_reaches_world_transaction_and_preserves_cancelled_state(
    tmp_path: Path,
) -> None:
    runtime = ExecutionRuntime()
    transactions = _BlockingTransactions()
    controller = RegionDeleteController(
        runtime.create_scope("region_delete_cancel_test"),
        cast(WorldTransactionService, transactions),
    )
    completed = threading.Event()
    outcomes: list[RegionDeleteOutcome] = []

    def on_complete(outcome: RegionDeleteOutcome) -> None:
        outcomes.append(outcome)
        completed.set()

    try:
        handle = controller.start(
            _request(tmp_path),
            on_complete,
        )
        assert transactions.started.wait(1)
        assert controller.cancel() is True
        transactions.release.set()
        with pytest.raises(WorldTransactionCancelledError):
            handle.result(timeout=1)
        assert completed.wait(1)
        assert outcomes[0].status is RegionDeleteStatus.CANCELLED
    finally:
        transactions.release.set()
        runtime.shutdown(wait=True)


def test_second_delete_is_rejected_while_first_is_running(
    tmp_path: Path,
) -> None:
    runtime = ExecutionRuntime()
    transactions = _BlockingTransactions()
    controller = RegionDeleteController(
        runtime.create_scope("region_delete_busy_test"),
        cast(WorldTransactionService, transactions),
    )

    try:
        first = controller.start(_request(tmp_path), lambda outcome: None)
        assert transactions.started.wait(1)
        with pytest.raises(RegionDeleteBusyError):
            controller.start(_request(tmp_path), lambda outcome: None)
        transactions.release.set()
        first.result(timeout=1)
    finally:
        transactions.release.set()
        runtime.shutdown(wait=True)
