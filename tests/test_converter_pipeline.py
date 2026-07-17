from pathlib import Path
from typing import Any

import core.converter as converter


class _Tracker:
    def __init__(self) -> None:
        self.files = 0
        self.errors = 0

    def increment_files(self, count: int = 1) -> None:
        self.files += count

    def increment_errors(self, count: int = 1) -> None:
        self.errors += count


def test_prepare_work_path_copies_world_and_ignores_transient_files(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    (source / "level.dat").write_text("level", encoding="utf-8")
    for name in ("cache.tmp", "level.dat.bak", "level.dat.old"):
        (source / name).write_text("ignored", encoding="utf-8")

    work_path = converter._prepare_work_path(source, destination)

    assert work_path == destination
    assert (destination / "level.dat").read_text(encoding="utf-8") == "level"
    assert not (destination / "cache.tmp").exists()
    assert not (destination / "level.dat.bak").exists()
    assert not (destination / "level.dat.old").exists()


def test_convert_nbt_files_isolates_file_failures(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    good_file = tmp_path / "good.dat"
    bad_file = tmp_path / "bad.nbt"
    ignored_file = tmp_path / "notes.txt"
    for path in (good_file, bad_file, ignored_file):
        path.touch()

    saved = []
    warnings = []
    tracker = _Tracker()
    result = converter.ConversionResult()

    monkeypatch.setattr(converter, "detect_endian", lambda _path: "big")

    def load(path: Path, byteorder: str) -> object:
        del byteorder
        if path == bad_file:
            raise converter.ConversionError("broken")
        return object()

    monkeypatch.setattr(converter, "load_nbt", load)
    monkeypatch.setattr(
        converter,
        "save_nbt",
        lambda path, _data, byteorder: saved.append((path, byteorder)),
    )

    converter._convert_nbt_files(
        tmp_path,
        "java",
        None,
        "big",
        result,
        tracker,
        lambda message, **_kwargs: warnings.append(message),
    )

    assert saved == [(good_file, "big")]
    assert result.converted_files == 1
    assert len(result.errors) == 1
    assert warnings == result.errors
    assert tracker.files == 1
    assert tracker.errors == 1


def test_convert_region_files_aggregates_worker_results(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    converted_file = tmp_path / "r.0.0.mca"
    broken_file = tmp_path / "r.1.0.mca"
    tracker = _Tracker()
    result = converter.ConversionResult()
    warnings = []

    monkeypatch.setattr(
        "core.scanner.scan_all_regions",
        lambda _path: [converted_file, broken_file],
    )

    def convert_one(
        path: Path,
        _platform: str,
        _version: int,
    ) -> tuple[bool, str | None]:
        if path == broken_file:
            return False, "broken region"
        return True, None

    monkeypatch.setattr(converter, "_convert_one_region", convert_one)

    converter._convert_region_files(
        tmp_path,
        "java",
        1,
        result,
        tracker,
        lambda message, **_kwargs: warnings.append(message),
    )

    assert result.converted_files == 1
    assert result.errors == ["broken region"]
    assert warnings == ["broken region"]
    assert tracker.files == 1
    assert tracker.errors == 1
