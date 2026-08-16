"""区块 NBT 路径换算与安全读取服务测试。"""
from __future__ import annotations

from pathlib import Path

import core.nbt as nbtlib
import pytest

from app.services.nbt_chunk_service import (
    ChunkMissingError,
    ChunkPathError,
    dimension_region_dir,
    load_chunk_payload,
    region_file_relative,
    world_coords_to_region_chunk,
)
from core.mca import WritableRegion


class _Session:
    def __init__(self, world_path: Path) -> None:
        self.world_path = world_path

    def load_chunk_nbt(
        self,
        region_path: Path,
        chunk_x: int,
        chunk_z: int,
    ) -> tuple[object, Path] | None:
        absolute = self.world_path / region_path
        if not absolute.is_file():
            return None
        from core.mca import RegionFile

        with RegionFile.open(absolute) as region:
            if not region.has_chunk(chunk_x, chunk_z):
                return None
            return region.read_chunk(chunk_x, chunk_z), absolute


def test_dimension_and_world_coord_helpers() -> None:
    assert dimension_region_dir("overworld") == "region"
    assert dimension_region_dir("the_nether") == "DIM-1/region"
    assert dimension_region_dir("the_end") == "DIM1/region"
    assert world_coords_to_region_chunk(520, -10) == (1, -1, 0, 31)
    assert region_file_relative("overworld", 1, -1) == "region/r.1.-1.mca"


def test_load_chunk_payload_reads_existing_chunk(tmp_path: Path) -> None:
    (tmp_path / "level.dat").write_bytes(b"")
    region_dir = tmp_path / "region"
    region_dir.mkdir()
    path = region_dir / "r.0.0.mca"
    writer = WritableRegion.empty(path)
    writer.set_chunk(2, 3, nbtlib.File({
        "Status": nbtlib.String("full"),
        "xPos": nbtlib.Int(2),
        "zPos": nbtlib.Int(3),
    }))
    writer.save(path, backup=False)

    result = load_chunk_payload(
        _Session(tmp_path),  # type: ignore[arg-type]
        Path("region/r.0.0.mca"),
        "region/r.0.0.mca",
        2,
        3,
    )
    assert result.chunk_x == 2
    assert result.chunk_z == 3
    assert str(result.data["Status"]) == "full"


def test_load_chunk_payload_rejects_missing_and_escape(tmp_path: Path) -> None:
    (tmp_path / "level.dat").write_bytes(b"")
    session = _Session(tmp_path)
    with pytest.raises(ChunkPathError):
        load_chunk_payload(
            session,  # type: ignore[arg-type]
            Path("region/r.0.0.mca"),
            "region/r.0.0.mca",
            0,
            0,
        )
    region_dir = tmp_path / "region"
    region_dir.mkdir()
    path = region_dir / "r.0.0.mca"
    writer = WritableRegion.empty(path)
    writer.set_chunk(0, 0, nbtlib.File({"Status": nbtlib.String("full")}))
    writer.save(path, backup=False)
    with pytest.raises(ChunkMissingError):
        load_chunk_payload(
            session,  # type: ignore[arg-type]
            Path("region/r.0.0.mca"),
            "region/r.0.0.mca",
            1,
            1,
        )
    with pytest.raises(ChunkPathError):
        load_chunk_payload(
            session,  # type: ignore[arg-type]
            Path("../outside.mca"),
            "../outside.mca",
            0,
            0,
        )
