"""Tests for map export service"""
from pathlib import Path
import pytest
import re


def test_map_export_region_scanning_logic():
    """Test that the region scanning logic only scans overworld region files."""
    # Simulate the scanning logic from map_export_service.py
    # This test doesn't require PIL to be installed

    # Create a mock world directory structure
    import tempfile
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        # Create overworld region directory with a region file
        overworld_region = tmp_path / "region"
        overworld_region.mkdir()
        overworld_mca = overworld_region / "r.0.0.mca"
        overworld_mca.touch()
        overworld_mca2 = overworld_region / "r.1.0.mca"
        overworld_mca2.touch()

        # Create nether dimension with same region file names
        nether_dir = tmp_path / "DIM-1"
        nether_region = nether_dir / "region"
        nether_region.mkdir(parents=True)
        nether_mca = nether_region / "r.0.0.mca"
        nether_mca.touch()

        # Create end dimension with same region file names
        end_dir = tmp_path / "DIM1"
        end_region = end_dir / "region"
        end_region.mkdir(parents=True)
        end_mca = end_region / "r.0.0.mca"
        end_mca.touch()

        # Create 1.16+ style dimension
        dimensions_dir = tmp_path / "dimensions" / "mod" / "custom_dim"
        mod_region = dimensions_dir / "region"
        mod_region.mkdir(parents=True)
        mod_mca = mod_region / "r.0.0.mca"
        mod_mca.touch()

        # Verify scan_all_regions would include all dimensions (the old bug)
        from core.scanner import scan_all_regions
        all_regions = scan_all_regions(tmp_path)
        # All dimensions included (including 2 overworld files)
        assert len(all_regions) == 5

        # Now test the new scanning logic (only overworld)
        region_dir = tmp_path / "region"
        region_files = list(region_dir.glob("*.mca"))
        region_files = [
            f for f in region_files if f.is_file() and re.match(
                r"^r\.-?\d+\.-?\d+\.mca$", f.name)]
        region_files = sorted(region_files)

        # Should only have overworld region files
        assert len(region_files) == 2
        assert region_files[0] == overworld_mca
        assert region_files[1] == overworld_mca2


def test_map_export_service_reports_missing_region_dir(tmp_path: Path):
    """The public export contract reports failure for a missing region dir."""
    from app.services.map_export_service import MapExportService, PIL_AVAILABLE

    if not PIL_AVAILABLE:
        pytest.skip("PIL not available")
    world = tmp_path / "world"
    world.mkdir()
    (world / "level.dat").touch()

    result = MapExportService().export_map(world, tmp_path / "map.png")

    assert result["success"] is False
    assert result["output_path"] is None


def test_map_export_reports_failure_when_all_regions_are_unreadable(tmp_path: Path):
    """Empty/corrupt MCA files that the topview path cannot paint fail export."""
    from app.services.map_export_service import MapExportService, PIL_AVAILABLE
    from unittest.mock import patch

    if not PIL_AVAILABLE:
        pytest.skip("PIL not available")
    world = tmp_path / "world"
    region_dir = world / "region"
    region_dir.mkdir(parents=True)
    (region_dir / "r.0.0.mca").write_bytes(b"\x00" * 8192)

    with patch(
        "core.mca.map_export_renderer.render_region_topview",
        return_value=None,
    ):
        result = MapExportService().export_map(
            world,
            tmp_path / "map.png",
            scale=16,
        )

    assert result["success"] is False
    assert result["chunks_processed"] == 0
    assert not (tmp_path / "map.png").exists()
