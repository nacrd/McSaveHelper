import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.services.save_repair import chunk_repairer, detector
from app.services.save_repair.chunk_repairer import ChunkRepairer
from app.services.save_repair.detector import WorldDetector


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


def test_chunk_repair_region_counts_invalid_slots_and_closes_region(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    fake_region = _Region()
    monkeypatch.setattr(
        chunk_repairer,
        "Region",
        SimpleNamespace(from_file=lambda _path: fake_region),
    )
    monkeypatch.setattr(chunk_repairer, "validate_chunk", lambda _chunk: False)

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
    monkeypatch.setattr(
        chunk_repairer,
        "Region",
        SimpleNamespace(from_file=lambda _path: (_ for _ in ()).throw(
            OSError("unreadable")
        )),
    )
    repairer = ChunkRepairer(threading.Event())
    quarantined = []
    monkeypatch.setattr(
        repairer,
        "_quarantine_file",
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
    monkeypatch.setattr(
        detector,
        "Region",
        SimpleNamespace(from_file=lambda _path: fake_region),
    )
    monkeypatch.setattr(detector, "validate_chunk", lambda _chunk: False)
    world_detector = WorldDetector(threading.Event())

    result = world_detector._detect_region(
        tmp_path / "r.0.0.mca",
        lambda _message, _level: None,
    )

    assert result.damaged_chunks == 2
    assert result.unreadable_error is None
    assert fake_region.closed is True

    monkeypatch.setattr(
        detector,
        "Region",
        SimpleNamespace(from_file=lambda _path: (_ for _ in ()).throw(
            OSError("unreadable")
        )),
    )
    unreadable = world_detector._detect_region(
        tmp_path / "r.1.0.mca",
        lambda _message, _level: None,
    )
    assert unreadable.damaged_chunks == 0
    assert unreadable.unreadable_error == "无法读取: unreadable"
