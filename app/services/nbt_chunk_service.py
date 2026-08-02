"""世界内区块 NBT 的安全路径校验与读取服务。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from app.services.execution_runtime import CancellationToken
from core.mca.map_models import BLOCKS_PER_CHUNK, BLOCKS_PER_REGION, CHUNKS_PER_REGION
from core.omni.world_session import WorldSession


class ChunkPathError(ValueError):
    """区块加载路径不满足当前存档边界或文件格式约束。"""


class ChunkMissingError(LookupError):
    """区域文件存在但目标区块没有可读数据。"""


@dataclass(frozen=True)
class ChunkLoadResult:
    """后台区块读取结果，供 UI 线程一次性投影。"""

    region_path: Path
    relative_text: str
    chunk_x: int
    chunk_z: int
    data: Any


def dimension_region_dir(dimension: str) -> str:
    """返回维度对应的世界相对区域目录。

    Args:
        dimension: 维度 id（如 ``overworld`` / ``the_nether``）。

    Returns:
        Java 版世界根目录下的相对 region 目录。
    """
    if dimension in {"the_nether", "minecraft:the_nether", "DIM-1"}:
        return "DIM-1/region"
    if dimension in {"the_end", "minecraft:the_end", "DIM1"}:
        return "DIM1/region"
    if dimension and dimension not in {"overworld", "minecraft:overworld"}:
        cleaned = dimension.replace(":", "/")
        return f"dimensions/{cleaned}/region"
    return "region"


def world_coords_to_region_chunk(
    world_x: int,
    world_z: int,
) -> tuple[int, int, int, int]:
    """把世界方块坐标换算为区域坐标与区域内区块坐标。

    Returns:
        ``(region_x, region_z, local_chunk_x, local_chunk_z)``。
    """
    chunk_x = world_x // BLOCKS_PER_CHUNK
    chunk_z = world_z // BLOCKS_PER_CHUNK
    region_x = chunk_x // CHUNKS_PER_REGION
    region_z = chunk_z // CHUNKS_PER_REGION
    local_x = chunk_x - region_x * CHUNKS_PER_REGION
    local_z = chunk_z - region_z * CHUNKS_PER_REGION
    return region_x, region_z, local_x, local_z


def region_file_relative(
    dimension: str,
    region_x: int,
    region_z: int,
) -> str:
    """构造区域文件的世界相对 POSIX 路径。"""
    base = dimension_region_dir(dimension)
    return f"{base}/r.{region_x}.{region_z}.mca"


def load_chunk_payload(
    session: WorldSession,
    relative_path: Path,
    relative_text: str,
    chunk_x: int,
    chunk_z: int,
    token: Optional[CancellationToken] = None,
) -> ChunkLoadResult:
    """校验区域路径并读取目标区块。

    Args:
        session: 当前世界会话。
        relative_path: 世界内区域文件相对路径。
        relative_text: 用户输入的路径文本，用于错误说明。
        chunk_x: 区域内区块 X（0–31）。
        chunk_z: 区域内区块 Z（0–31）。
        token: 可选协作取消令牌。

    Returns:
        可安全投影到 UI 的区块读取结果。

    Raises:
        ChunkPathError: 路径越界、穿过链接或不是现有 MCA 文件。
        ChunkMissingError: 目标区块不存在或不可读。
        ValueError: 区块坐标越界。
    """
    if not (0 <= chunk_x < CHUNKS_PER_REGION and 0 <= chunk_z < CHUNKS_PER_REGION):
        raise ValueError(
            f"区块坐标必须在 0..{CHUNKS_PER_REGION - 1} 内"
        )
    if relative_path.is_absolute():
        raise ChunkPathError("区域文件必须使用当前存档内的相对路径。")

    world_root = session.world_path.resolve()
    candidate = world_root / relative_path
    _reject_link_components(candidate, world_root)
    region_path = candidate.resolve()
    try:
        canonical_relative = region_path.relative_to(world_root)
    except ValueError as exc:
        raise ChunkPathError("区域文件必须位于当前存档目录内。") from exc
    if region_path.suffix.lower() != ".mca" or not region_path.is_file():
        raise ChunkPathError(
            f"区域文件不存在或不是 .mca 文件: {relative_text}"
        )
    _raise_if_cancelled(token)
    result = session.load_chunk_nbt(canonical_relative, chunk_x, chunk_z)
    _raise_if_cancelled(token)
    if result is None:
        raise ChunkMissingError("该区块不存在或无法读取。")
    chunk_data, _absolute_path = result
    return ChunkLoadResult(
        region_path=canonical_relative,
        relative_text=canonical_relative.as_posix(),
        chunk_x=chunk_x,
        chunk_z=chunk_z,
        data=chunk_data,
    )


def _reject_link_components(candidate: Path, world_root: Path) -> None:
    """拒绝穿过存档内符号链接或 junction 的外部路径。"""
    try:
        relative = candidate.relative_to(world_root)
    except ValueError:
        return
    current = world_root
    for component in relative.parts:
        current /= component
        is_junction = getattr(current, "is_junction", None)
        if current.is_symlink() or (
            callable(is_junction) and is_junction()
        ):
            raise ChunkPathError("区域文件路径不能穿过符号链接或 junction。")


def _raise_if_cancelled(token: Optional[CancellationToken]) -> None:
    if token is not None:
        token.raise_if_cancelled()


__all__ = [
    "BLOCKS_PER_REGION",
    "ChunkLoadResult",
    "ChunkMissingError",
    "ChunkPathError",
    "dimension_region_dir",
    "load_chunk_payload",
    "region_file_relative",
    "world_coords_to_region_chunk",
]
