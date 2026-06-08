from pathlib import Path

from core.region_utils import parse_region_coords, scan_region_dir, scan_regions


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
