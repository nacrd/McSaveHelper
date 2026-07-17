from pathlib import Path

from core.omni.world_scanner import WorldScanner


def _create_region_file(region_dir: Path, name: str = "r.0.0.mca") -> Path:
    region_dir.mkdir(parents=True, exist_ok=True)
    region_file = region_dir / name
    region_file.write_bytes(b"")
    return region_file


def test_dimension_scan_discovers_colliding_region_coordinates(
    tmp_path: Path,
) -> None:
    overworld_file = _create_region_file(tmp_path / "region")
    modern_overworld = _create_region_file(
        tmp_path / "dimensions" / "minecraft" / "overworld" / "region",
        "r.2.0.mca",
    )
    modern_nether = _create_region_file(
        tmp_path / "dimensions" / "minecraft" / "the_nether" / "region",
    )
    _create_region_file(tmp_path / "DIM-1" / "region", "r.1.0.mca")
    custom_dimension = _create_region_file(
        tmp_path / "dimensions" / "example" / "moon" / "region",
        "r.-1.2.mca",
    )

    scanner = WorldScanner(tmp_path)
    dimensions = scanner.scan_dimensions({(0, 0): overworld_file})
    by_id = {dimension["id"]: dimension for dimension in dimensions}

    assert list(by_id) == ["overworld", "minecraft:the_nether", "example:moon"]
    assert by_id["overworld"]["region_dir"] == str(modern_overworld.parent)
    assert by_id["minecraft:the_nether"]["region_dir"] == str(
        modern_nether.parent
    )
    assert by_id["example:moon"]["region_dir"] == str(custom_dimension.parent)


def test_dimension_scan_ignores_directories_without_region_files(
    tmp_path: Path,
) -> None:
    (tmp_path / "region").mkdir()
    (tmp_path / "dimensions" / "example" / "empty" / "region").mkdir(
        parents=True
    )

    assert WorldScanner(tmp_path).scan_dimensions({}) == []
