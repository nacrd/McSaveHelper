"""Explorer NBT 数据源的纯 I/O 与路径安全操作。"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Optional

import core.nbt as nbtlib
from app.services.execution_runtime import CancellationToken
from app.ui.views.explorer.nbt_tree.exporter import to_serializable
from core.io_atomic import atomic_write_text
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


def find_nbt_target_candidates(
    world_path: Path,
    token: Optional[CancellationToken] = None,
) -> list[tuple[str, Path]]:
    """扫描世界内可直接编辑的 NBT 与 JSON 文件。

    Args:
        world_path: 当前世界根目录。
        token: 可选协作取消令牌。

    Returns:
        按稳定顺序排列的展示标签和世界相对路径。
    """
    _raise_if_cancelled(token)
    candidates: list[tuple[str, Path]] = []
    if (world_path / "level.dat").exists():
        candidates.append(("世界 / level.dat", Path("level.dat")))
    candidates.extend(
        (f"数据 / {path.name}", path.relative_to(world_path))
        for path in sorted((world_path / "data").glob("*.dat"))
    )
    _raise_if_cancelled(token)
    for folder_name, label in (("stats", "统计"), ("advancements", "进度")):
        candidates.extend(
            (f"{label} / {path.name}", path.relative_to(world_path))
            for path in sorted((world_path / folder_name).glob("*.json"))
        )
        _raise_if_cancelled(token)
    return candidates


def load_world_nbt(
    world_root: Path,
    relative_path: Path,
    token: Optional[CancellationToken],
) -> Any:
    """安全加载当前世界内的一个 ``.dat`` 文件。

    Args:
        world_root: 当前世界根目录。
        relative_path: 世界根目录内的相对路径。
        token: 可选协作取消令牌。

    Returns:
        保留标签类型的 NBT 文件对象。

    Raises:
        ValueError: 路径为绝对路径、越界或穿过链接。
        FileNotFoundError: 文件不存在或扩展名不匹配。
    """
    path = _resolve_world_file(world_root, relative_path, ".dat")
    _raise_if_cancelled(token)
    result = nbtlib.load(path)
    _raise_if_cancelled(token)
    return result


def load_world_json(
    world_root: Path,
    relative_path: Path,
    token: Optional[CancellationToken],
) -> Any:
    """安全加载当前世界内的一个 JSON 文件。

    Args:
        world_root: 当前世界根目录。
        relative_path: 世界根目录内的相对路径。
        token: 可选协作取消令牌。

    Returns:
        JSON 解码后的 Python 值。

    Raises:
        ValueError: 路径为绝对路径、越界或穿过链接。
        FileNotFoundError: 文件不存在或扩展名不匹配。
        json.JSONDecodeError: 文件内容不是有效 JSON。
    """
    path = _resolve_world_file(world_root, relative_path, ".json")
    _raise_if_cancelled(token)
    with path.open("r", encoding="utf-8") as file:
        result = json.load(file)
    _raise_if_cancelled(token)
    return result


def load_chunk_payload(
    session: WorldSession,
    relative_path: Path,
    relative_text: str,
    chunk_x: int,
    chunk_z: int,
    token: Optional[CancellationToken],
) -> ChunkLoadResult:
    """校验区域路径并读取目标区块。

    Args:
        session: 当前世界会话。
        relative_path: 世界内区域文件相对路径。
        relative_text: 用户输入的路径文本，用于错误说明。
        chunk_x: 区块 X 坐标。
        chunk_z: 区块 Z 坐标。
        token: 可选协作取消令牌。

    Returns:
        可安全投影到 UI 的区块读取结果。

    Raises:
        ChunkPathError: 路径越界、穿过链接或不是现有 MCA 文件。
        ChunkMissingError: 目标区块不存在或不可读。
    """
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


def export_json_payload(
    data: Any,
    output_path: Path,
    token: Optional[CancellationToken],
) -> bool:
    """把 NBT 树快照写为 JSON，并观察取消请求。

    Args:
        data: 要导出的 NBT/JSON 树快照。
        output_path: 用户选择的输出路径。
        token: 可选协作取消令牌。

    Returns:
        成功写入时返回 True。

    Raises:
        OSError: 导出器未能写出目标文件。
    """
    if data is None:
        raise OSError("没有可导出的 NBT 数据")
    _raise_if_cancelled(token)
    content = json.dumps(
        to_serializable(data),
        ensure_ascii=False,
        indent=2,
    )
    _raise_if_cancelled(token)
    atomic_write_text(output_path, content)
    return True


def _resolve_world_file(
    world_root: Path,
    relative_path: Path,
    suffix: str,
) -> Path:
    """解析世界内文件，拒绝越界、链接和错误扩展名。"""
    if relative_path.is_absolute():
        raise ValueError("目标文件必须使用当前存档内的相对路径。")
    canonical_root = world_root.resolve()
    candidate = canonical_root / relative_path
    _reject_link_components(candidate, canonical_root)
    path = candidate.resolve()
    try:
        path.relative_to(canonical_root)
    except ValueError as exc:
        raise ValueError("目标文件必须位于当前存档目录内。") from exc
    if path.suffix.lower() != suffix or not path.is_file():
        raise FileNotFoundError(f"文件不存在或类型不匹配: {relative_path}")
    return path


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
            raise ChunkPathError(
                "区域文件路径不能穿过符号链接或 junction。"
            )


def _raise_if_cancelled(token: Optional[CancellationToken]) -> None:
    """在安全检查点传播协作取消。"""
    if token is not None:
        token.raise_if_cancelled()
