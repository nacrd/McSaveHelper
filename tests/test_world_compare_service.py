import os
from pathlib import Path

from app.services.world_compare_service import WorldCompareService


def _write_region(path: Path, content: bytes, mtime_ns: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    os.utime(path, ns=(mtime_ns, mtime_ns))


def test_region_comparison_keeps_same_coordinates_in_each_dimension(
    tmp_path: Path,
    monkeypatch,
) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    paths = []
    for world, overworld, nether in (
        (left, b"same", b"left-nether"),
        (right, b"same", b"right-nether"),
    ):
        for relative, content in (
            (Path("region/r.0.0.mca"), overworld),
            (Path("DIM-1/region/r.0.0.mca"), nether),
        ):
            path = world / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            paths.append(path)

    monkeypatch.setattr(
        "app.services.world_compare_service.scan_all_regions",
        lambda world: [path for path in paths if path.is_relative_to(world)],
    )

    compared = WorldCompareService()._compare_regions(left, right)

    assert [item.name for item in compared] == [
        "DIM-1/region/r.0.0.mca",
        "region/r.0.0.mca",
    ]
    assert [item.same for item in compared] == [False, True]


def test_region_comparison_skips_hash_for_matching_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left_region = left / "region/r.0.0.mca"
    right_region = right / "region/r.0.0.mca"
    _write_region(left_region, b"other", 1_000_000_000)
    _write_region(right_region, b"right", 1_000_000_000)
    monkeypatch.setattr(
        "app.services.world_compare_service.scan_all_regions",
        lambda world: [left_region] if world == left else [right_region],
    )
    monkeypatch.setattr(
        "app.services.world_compare_service.hashlib.sha256",
        lambda: (_ for _ in ()).throw(AssertionError("unexpected hash")),
    )

    compared = WorldCompareService()._compare_regions(left, right)

    assert compared[0].same is True
    assert "sha256" not in compared[0].left
    assert "sha256" not in compared[0].right


def test_region_comparison_hashes_equal_size_with_different_mtime(
    tmp_path: Path,
    monkeypatch,
) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left_region = left / "region/r.0.0.mca"
    right_region = right / "region/r.0.0.mca"
    _write_region(left_region, b"same", 1_000_000_000)
    _write_region(right_region, b"same", 2_000_000_000)
    monkeypatch.setattr(
        "app.services.world_compare_service.scan_all_regions",
        lambda world: [left_region] if world == left else [right_region],
    )

    compared = WorldCompareService()._compare_regions(left, right)

    assert compared[0].same is True
    assert compared[0].left["sha256"] == compared[0].right["sha256"]


def test_region_comparison_skips_hash_when_sizes_differ(
    tmp_path: Path,
    monkeypatch,
) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left_region = left / "region/r.0.0.mca"
    right_region = right / "region/r.0.0.mca"
    _write_region(left_region, b"short", 1_000_000_000)
    _write_region(right_region, b"longer", 2_000_000_000)
    monkeypatch.setattr(
        "app.services.world_compare_service.scan_all_regions",
        lambda world: [left_region] if world == left else [right_region],
    )
    monkeypatch.setattr(
        "app.services.world_compare_service.hashlib.sha256",
        lambda: (_ for _ in ()).throw(AssertionError("unexpected hash")),
    )

    compared = WorldCompareService()._compare_regions(left, right)

    assert compared[0].same is False
