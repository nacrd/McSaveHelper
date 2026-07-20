import threading
from pathlib import Path
from typing import Any

from app.services.save_repair import chunk_repairer, detector
from app.services.save_repair.chunk_repairer import ChunkRepairer
from app.services.save_repair.detector import WorldDetector
from app.services.save_repair import validation_utils


class _Region:
    def __init__(self) -> None:
        self.closed = False

    def __enter__(self) -> "_Region":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.closed = True

    def get_chunk(self, chunk_x: int, chunk_z: int) -> object | None:
        if (chunk_x, chunk_z) == (0, 0):
            return object()
        if (chunk_x, chunk_z) == (0, 1):
            raise ValueError("corrupt slot")
        return None


def _patch_damaged_scan(
    monkeypatch: Any,
    module: Any,
    *,
    region: _Region | None = None,
    error: Exception | None = None,
) -> None:
    """Route region opens through the shared count_damaged_chunks helper."""

    def _count(
        region_file: Path,
        is_cancelled: Any,
        region_factory: Any = None,
    ) -> tuple[int, bool]:
        if error is not None:
            raise error
        assert region is not None
        return validation_utils.count_damaged_chunks(
            region_file,
            is_cancelled,
            region_factory=lambda _path: region,
        )

    monkeypatch.setattr(module, "count_damaged_chunks", _count)
    monkeypatch.setattr(validation_utils, "validate_chunk", lambda _chunk: False)


def test_chunk_repair_region_counts_invalid_slots_and_closes_region(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    fake_region = _Region()
    _patch_damaged_scan(monkeypatch, chunk_repairer, region=fake_region)

    result = ChunkRepairer(threading.Event())._repair_region(
        tmp_path / "r.0.0.mca",
        lambda _message, _level: None,
    )

    assert result.checked_regions == 1
    assert result.damaged_chunks == 2
    assert result.quarantined_regions == 0
    assert fake_region.closed is True


def test_chunk_repair_region_quarantines_unreadable_file(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _patch_damaged_scan(
        monkeypatch,
        chunk_repairer,
        error=OSError("unreadable"),
    )
    repairer = ChunkRepairer(threading.Event())
    quarantined: list[Path] = []
    monkeypatch.setattr(
        chunk_repairer,
        "quarantine_file",
        lambda path, _log: quarantined.append(path),
    )
    region_file = tmp_path / "r.0.0.mca"

    result = repairer._repair_region(
        region_file,
        lambda _message, _level: None,
    )

    assert result.quarantined_regions == 1
    assert quarantined == [region_file]


def test_detector_region_reports_damage_and_read_errors(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    fake_region = _Region()
    _patch_damaged_scan(monkeypatch, detector, region=fake_region)
    world_detector = WorldDetector(threading.Event())

    result = world_detector._detect_region(
        tmp_path / "r.0.0.mca",
        lambda _message, _level: None,
    )

    assert result.damaged_chunks == 2
    assert result.unreadable_error is None
    assert fake_region.closed is True

    _patch_damaged_scan(
        monkeypatch,
        detector,
        error=OSError("unreadable"),
    )
    unreadable = world_detector._detect_region(
        tmp_path / "r.1.0.mca",
        lambda _message, _level: None,
    )
    assert unreadable.damaged_chunks == 0
    assert unreadable.unreadable_error == "无法读取: unreadable"
