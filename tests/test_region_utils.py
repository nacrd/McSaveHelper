from pathlib import Path

from core.region_utils import (
    discover_dimension_region_dirs,
    parse_region_coords,
    scan_region_dir,
    scan_regions,
)


def test_parse_region_coords_accepts_valid_names():
    assert parse_region_coords("r.0.0.mca") == (0, 0)
    assert parse_region_coords("r.-1.2.mca") == (-1, 2)
    assert parse_region_coords(Path("r.12.-34.mca")) == (12, -34)


def test_parse_region_coords_rejects_invalid_names():
    assert parse_region_coords("r.0.0") is None
    assert parse_region_coords("r.0.0.mcr") is None
    assert parse_region_coords("region.0.0.mca") is None
    assert parse_region_coords("r.a.0.mca") is None


def test_scan_region_dir_filters_and_sorts(tmp_path):
    region_dir = tmp_path / "region"
    region_dir.mkdir()
    valid_b = region_dir / "r.1.0.mca"
    valid_a = region_dir / "r.-1.0.mca"
    invalid = region_dir / "r.bad.0.mca"
    valid_b.touch()
    invalid.touch()
    valid_a.touch()

    assert scan_region_dir(region_dir) == [valid_a, valid_b]


def test_scan_regions_can_include_or_exclude_dimensions(tmp_path):
    overworld = tmp_path / "region"
    nether = tmp_path / "DIM-1" / "region"
    custom = tmp_path / "dimensions" / "mod" / "custom" / "region"
    overworld.mkdir(parents=True)
    nether.mkdir(parents=True)
    custom.mkdir(parents=True)
    overworld_file = overworld / "r.0.0.mca"
    nether_file = nether / "r.1.0.mca"
    custom_file = custom / "r.2.0.mca"
    overworld_file.touch()
    nether_file.touch()
    custom_file.touch()

    assert scan_regions(tmp_path, include_dimensions=False) == [overworld_file]
    assert scan_regions(tmp_path) == [nether_file, custom_file, overworld_file]


def test_discover_dimension_region_dirs_prefers_modern_paths(tmp_path):
    overworld = tmp_path / "region"
    modern_overworld = tmp_path / "dimensions" / "minecraft" / "overworld" / "region"
    modern_nether = tmp_path / "dimensions" / "minecraft" / "the_nether" / "region"
    legacy_nether = tmp_path / "DIM-1" / "region"
    custom = tmp_path / "dimensions" / "mod" / "custom" / "region"
    for path in (overworld, modern_overworld, modern_nether, legacy_nether, custom):
        path.mkdir(parents=True)
        (path / "r.0.0.mca").touch()

    discovered = discover_dimension_region_dirs(tmp_path)
    by_id = {item.id: item for item in discovered}

    assert list(by_id) == ["overworld", "minecraft:the_nether", "mod:custom"]
    assert by_id["overworld"].region_dir == modern_overworld
    assert by_id["minecraft:the_nether"].region_dir == modern_nether
    assert by_id["mod:custom"].region_dir == custom
