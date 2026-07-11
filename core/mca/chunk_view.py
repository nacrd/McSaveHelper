"""Anvil-compatible chunk/region adapters over native MCA reads."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple, Union

from core.mca.block_palette import ChunkBlocks, get_chunk_blocks
from core.mca.errors import ChunkMissing, CorruptChunk, McaError
from core.mca.nbt_access import as_int, first_key
from core.mca.region_file import RegionFile
from core.mca.versions import section_y_range
from core.region_utils import parse_region_coords

PathLike = Union[str, Path]


@dataclass(frozen=True)
class NamedBlock:
    id: str

    def name(self) -> str:
        return self.id

    def __str__(self) -> str:
        return self.id


class ChunkView:
    __slots__ = ("data", "x", "z", "version", "_blocks")

    def __init__(self, nbt: Any, world_cx: int, world_cz: int, blocks: Optional[ChunkBlocks] = None) -> None:
        self.data = nbt
        self.x = int(world_cx)
        self.z = int(world_cz)
        self._blocks = blocks or get_chunk_blocks(nbt)
        self.version = int(self._blocks.version or 0)
        try:
            root = self._blocks.root or nbt
            xpos = as_int(first_key(root, "xPos"))
            zpos = as_int(first_key(root, "zPos"))
            if xpos is not None:
                self.x = xpos
            if zpos is not None:
                self.z = zpos
        except Exception:
            pass

    def get_block(self, x: int, y: int, z: int) -> NamedBlock:
        name = self._blocks.block_id_at(x, y, z) or "minecraft:air"
        return NamedBlock(name)

    def get_palette(self, section_y: int) -> Optional[List[NamedBlock]]:
        names = self._blocks.get_palette_names(int(section_y))
        if not names:
            return None
        return [NamedBlock(n) for n in names]

    def section_ys(self) -> Sequence[int]:
        if self._blocks.section_ys_desc:
            return list(reversed(self._blocks.section_ys_desc))
        return list(section_y_range(self.version or None))


def region_coords_from_path(path: PathLike) -> Tuple[int, int]:
    coords = parse_region_coords(Path(path))
    if coords is None:
        return 0, 0
    return coords


def get_chunk(
    region: RegionFile,
    local_cx: int,
    local_cz: int,
    region_x: Optional[int] = None,
    region_z: Optional[int] = None,
) -> Optional[ChunkView]:
    try:
        nbt = region.read_chunk(local_cx, local_cz)
    except ChunkMissing:
        return None
    except Exception:
        return None

    if region_x is None or region_z is None:
        if region.path is not None:
            region_x, region_z = region_coords_from_path(region.path)
        else:
            region_x, region_z = 0, 0
    return ChunkView(nbt, region_x * 32 + local_cx, region_z * 32 + local_cz)


class NativeRegion:
    __slots__ = ("_rf", "_rx", "_rz")

    def __init__(self, rf: RegionFile, region_x: int = 0, region_z: int = 0) -> None:
        self._rf = rf
        self._rx = region_x
        self._rz = region_z

    @classmethod
    def from_file(cls, path: PathLike) -> "NativeRegion":
        p = Path(path)
        rf = RegionFile.open(p)
        rx, rz = region_coords_from_path(p)
        return cls(rf, rx, rz)

    def get_chunk(self, local_cx: int, local_cz: int) -> Optional[ChunkView]:
        return get_chunk(self._rf, local_cx, local_cz, self._rx, self._rz)

    def close(self) -> None:
        self._rf.close()

    def __enter__(self) -> "NativeRegion":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


def section_range_for_chunk(chunk: Any) -> range:
    version = getattr(chunk, "version", None)
    try:
        return section_y_range(int(version) if version is not None else None)
    except Exception:
        return range(-4, 20)
