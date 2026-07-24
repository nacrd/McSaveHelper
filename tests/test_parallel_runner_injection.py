"""ParallelRunner injection contracts for core migration algorithms."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional, Sequence, TypeVar

import pytest

import core.converter as converter
import core.fast_mode as fast_mode
import core.full_mode as full_mode
import core.mca.surface as surface
import core.pure_cleaner as pure_cleaner
import core.worker as worker
from core.parallel import ParallelRunner


ItemT = TypeVar("ItemT")
ResultT = TypeVar("ResultT")


class RecordingRunner:
    """Small deterministic runner used to verify the injected boundary."""

    def __init__(self) -> None:
        self.operations: list[tuple[str, Optional[int], int]] = []

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
        self.operations.append((operation, max_workers, len(items)))
        results: list[ResultT | BaseException] = []
        for index, item in enumerate(items):
            if cancel_check is not None and cancel_check():
                raise RuntimeError("cancelled")
            try:
                value: ResultT | BaseException = worker(item)
            except Exception as exc:
                value = exc
            results.append(value)
            if on_item_done is not None:
                on_item_done(index, value)
        return results


def test_region_worker_uses_injected_runner_and_reports_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = RecordingRunner()
    files = [Path("r.0.0.mca"), Path("r.1.0.mca")]
    monkeypatch.setattr(
        worker,
        "process_region_file",
        lambda path, _mappings: (str(path), 2, None),
    )
    progress: list[float] = []
    logs: list[tuple[str, str]] = []

    changes = worker.process_regions_parallel(
        files,
        [],
        progress.append,
        lambda message, level: logs.append((message, level)),
        max_workers=99,
        parallel_runner=runner,
    )

    assert changes == 4
    assert progress == [0.5, 1.0]
    assert runner.operations == [("migration.patch-regions", 2, 2)]


def test_pure_cleaner_uses_injected_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = RecordingRunner()
    region = tmp_path / "r.0.0.mca"
    monkeypatch.setattr(pure_cleaner, "scan_all_regions", lambda _path: [region])
    monkeypatch.setattr(
        pure_cleaner,
        "scan_all_entity_regions",
        lambda _path: [],
    )
    monkeypatch.setattr(
        pure_cleaner,
        "_process_one_region",
        lambda _path: ("r.0.0.mca", 3, 1, 2, None),
    )

    assert pure_cleaner.purge_mod_blocks_and_entities(
        tmp_path,
        lambda _message, _level: None,
        parallel_runner=runner,
    )
    assert runner.operations == [("migration.purge-regions", 1, 1)]


def test_converter_uses_injected_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = RecordingRunner()
    region = tmp_path / "r.0.0.mca"
    monkeypatch.setattr("core.scanner.scan_all_regions", lambda _path: [region])
    monkeypatch.setattr(
        converter,
        "_convert_one_region",
        lambda _path, _platform, _version: (True, None),
    )

    class Tracker:
        def __init__(self) -> None:
            self.files = 0

        def increment_files(self, count: int = 1) -> None:
            self.files += count

        def increment_errors(self, count: int = 1) -> None:
            del count

    result = converter.ConversionResult()
    tracker = Tracker()
    converter._convert_region_files(
        tmp_path,
        "java",
        1,
        result,
        tracker,
        lambda _message, **_kwargs: None,
        runner,
    )

    assert result.converted_files == 1
    assert tracker.files == 1
    assert runner.operations == [("converter.region-files", 1, 1)]


def test_surface_decoder_uses_injected_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = RecordingRunner()
    monkeypatch.setattr(
        surface,
        "_decode_one",
        lambda _region, chunk_x, chunk_z, _samples: (
            (chunk_x, chunk_z),
            {(0, 0): "minecraft:stone"},
        ),
    )
    surface.clear_chunk_decode_cache()
    views: dict[tuple[int, int], Optional[Any]] = {}
    surface._decode_misses_with_runner(
        object(),
        [(0, 0, [(0, 0)]), (1, 0, [(0, 0)])],
        "region",
        1,
        2,
        views,
        0,
        workers=8,
        failed_chunks=set(),
        external_signatures={},
        parallel_runner=runner,
    )

    assert set(views) == {(0, 0), (1, 0)}
    assert runner.operations == [("mca.surface.decode-chunks", 2, 2)]
    surface.clear_chunk_decode_cache()


def test_fast_and_full_modes_forward_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = RecordingRunner()
    captured: list[ParallelRunner] = []
    monkeypatch.setattr(
        fast_mode,
        "purge_mod_blocks_and_entities",
        lambda _path, _log, **kwargs: captured.append(kwargs["parallel_runner"])
        or True,
    )
    fast_mode._apply_fast_mode_cleanup(
        tmp_path,
        False,
        True,
        lambda _message, _level: None,
        1,
        runner,
        None,
    )

    region = tmp_path / "r.0.0.mca"
    monkeypatch.setattr(full_mode, "scan_all_regions", lambda _path: [region])
    monkeypatch.setattr(
        full_mode,
        "process_regions_parallel",
        lambda *_args, **kwargs: captured.append(kwargs["parallel_runner"]),
    )
    full_mode._process_regions(
        tmp_path,
        [],
        lambda _value: None,
        lambda _message, _level: None,
        1,
        runner,
        None,
    )

    assert captured == [runner, runner]
