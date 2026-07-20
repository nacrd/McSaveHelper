"""基于原生 MCA 读取的 Anvil 兼容 chunk/region 适配层。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, List, Optional, Sequence, Tuple, Union

from core.mca.block_palette import ChunkBlocks, get_chunk_blocks
from core.mca.errors import ChunkMissing
from core.mca.nbt_access import as_int, first_key
from core.mca.region_file import RegionFile
from core.mca.versions import section_y_range
from core.region_utils import parse_region_coords

PathLike = Union[str, Path]


@dataclass(frozen=True)
class NamedBlock:
    """具名方块标识（仅 ID，不含属性）。

    用于俯视/调试等只需资源名的场景，避免拉起完整 block state。
    """

    id: str

    def name(self) -> str:
        """返回方块资源 ID。"""
        return self.id

    def __str__(self) -> str:
        return self.id


class ChunkView:
    """单区块的只读视图：坐标、版本与方块查询。

    优先采用 NBT 内 xPos/zPos；缺失时回退到构造时的世界 chunk 坐标。
    """

    __slots__ = ("data", "x", "z", "version", "_blocks")

    def __init__(
        self,
        nbt: Any,
        world_cx: int,
        world_cz: int,
        blocks: Optional[ChunkBlocks] = None,
    ) -> None:
        """从区块 NBT 构建视图。

        Args:
            nbt: 区块 NBT 根（compound / File）。
            world_cx: 回退用的世界 chunk X。
            world_cz: 回退用的世界 chunk Z。
            blocks: 可选预解析的 ``ChunkBlocks``，避免重复解码。
        """
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
        except (TypeError, ValueError, AttributeError, KeyError):
            pass

    def get_block(self, x: int, y: int, z: int) -> NamedBlock:
        """查询区块内局部坐标的方块。

        Args:
            x: 局部 X（0–15）。
            y: 世界 Y。
            z: 局部 Z（0–15）。

        Returns:
            NamedBlock: 方块 ID；缺失时视为 air。
        """
        name = self._blocks.block_id_at(x, y, z) or "minecraft:air"
        return NamedBlock(name)

    def get_palette(self, section_y: int) -> Optional[List[NamedBlock]]:
        """返回指定 section 的调色板名称列表。

        Args:
            section_y: section 的 Y 索引。

        Returns:
            Optional[List[NamedBlock]]: 调色板；无 section 或空调色板时为 None。
        """
        names = self._blocks.get_palette_names(int(section_y))
        if not names:
            return None
        return [NamedBlock(n) for n in names]

    def section_ys(self) -> Sequence[int]:
        """返回本区块存在的 section Y（升序）。

        无解析 section 时按 DataVersion 回退到默认高度范围。
        """
        if self._blocks.section_ys_desc:
            return list(reversed(self._blocks.section_ys_desc))
        return list(section_y_range(self.version or None))


def region_coords_from_path(path: PathLike) -> Tuple[int, int]:
    """从 ``r.X.Z.mca`` 路径解析区域坐标。

    Args:
        path: 区域文件路径。

    Returns:
        Tuple[int, int]: ``(rx, rz)``；无法解析时返回 ``(0, 0)``。
    """
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
    """从 RegionFile 读取局部区块并包装为 ChunkView。

    损坏或缺失区块返回 None，避免扫描稀疏/模组区时中断整图。

    Args:
        region: 打开的区域文件。
        local_cx: 区域内局部 chunk X（0–31）。
        local_cz: 区域内局部 chunk Z（0–31）。
        region_x: 区域 X；缺省时从 path 解析。
        region_z: 区域 Z；缺省时从 path 解析。

    Returns:
        Optional[ChunkView]: 成功时的区块视图。
    """
    try:
        nbt = region.read_chunk(local_cx, local_cz)
    except ChunkMissing:
        return None
    except (OSError, ValueError, TypeError, RuntimeError, KeyError):
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
    """对单个 RegionFile 的轻量适配：按世界坐标取 ChunkView。"""

    __slots__ = ("_rf", "_rx", "_rz")

    def __init__(self, rf: RegionFile, region_x: int = 0, region_z: int = 0) -> None:
        """绑定已打开的 RegionFile 与区域坐标。

        Args:
            rf: 区域文件句柄。
            region_x: 区域 X。
            region_z: 区域 Z。
        """
        self._rf = rf
        self._rx = region_x
        self._rz = region_z

    @classmethod
    def from_file(cls, path: PathLike) -> "NativeRegion":
        """打开路径上的 .mca 并解析区域坐标。

        Args:
            path: ``r.X.Z.mca`` 路径。

        Returns:
            NativeRegion: 已打开的适配器（调用方负责 close）。
        """
        p = Path(path)
        rf = RegionFile.open(p)
        rx, rz = region_coords_from_path(p)
        return cls(rf, rx, rz)

    def get_chunk(self, local_cx: int, local_cz: int) -> Optional[ChunkView]:
        """读取局部区块视图。

        Args:
            local_cx: 局部 chunk X。
            local_cz: 局部 chunk Z。

        Returns:
            Optional[ChunkView]: 存在且可读时返回视图。
        """
        return get_chunk(self._rf, local_cx, local_cz, self._rx, self._rz)

    def iter_present_chunks(self) -> Iterable[Tuple[int, int]]:
        """遍历位置表非空槽的局部坐标。

        扫描稀疏/模组区时避免对 1024 槽逐个试探并抛缺块异常。

        Yields:
            Tuple[int, int]: ``(local_cx, local_cz)``。
        """
        return self._rf.iter_present_chunks()

    def iter_chunks(self) -> Iterator[Tuple[int, int, Optional[ChunkView]]]:
        """惰性遍历已存在坐标及其 ChunkView。

        Yields:
            Tuple[int, int, Optional[ChunkView]]: 局部坐标与视图（损坏时为 None）。
        """
        for local_cx, local_cz in self._rf.iter_present_chunks():
            yield local_cx, local_cz, self.get_chunk(local_cx, local_cz)

    def close(self) -> None:
        """关闭底层 RegionFile（幂等）。"""
        self._rf.close()

    def __enter__(self) -> "NativeRegion":
        """进入上下文管理器，返回 self。"""
        return self

    def __exit__(self, *args: Any) -> None:
        """退出时关闭底层 RegionFile。"""
        self.close()


def section_range_for_chunk(chunk: Any) -> range:
    """按区块 DataVersion 返回 section Y 的默认 range。

    Args:
        chunk: 具有可选 ``version`` 属性的对象（如 ChunkView）。

    Returns:
        range: section Y 范围；版本不可解析时回退 ``range(-4, 20)``。
    """
    version = getattr(chunk, "version", None)
    try:
        return section_y_range(int(version) if version is not None else None)
    except (TypeError, ValueError):
        return range(-4, 20)
