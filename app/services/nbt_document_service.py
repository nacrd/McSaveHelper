"""NBT 编辑器使用的世界内文档发现与安全读取服务。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Optional

import core.nbt as nbtlib
from app.services.execution_runtime import CancellationToken


NbtDocumentFormat = Literal["nbt", "json"]


class NbtDocumentPathError(ValueError):
    """NBT 文档目标越过世界边界或穿过链接时抛出。"""


@dataclass(frozen=True)
class NbtDocumentTarget:
    """一个可由 NBT 编辑器加载的世界相对文件。"""

    label: str
    relative_path: Path
    format: NbtDocumentFormat


@dataclass(frozen=True)
class LoadedNbtDocument:
    """后台读取完成后交付给 UI 的不可变文档身份与数据。"""

    target: NbtDocumentTarget
    data: Any


def find_nbt_documents(
    world_path: Path,
    token: Optional[CancellationToken] = None,
) -> tuple[NbtDocumentTarget, ...]:
    """发现世界内可编辑的 NBT 与 JSON 文档。

    Args:
        world_path: 当前 Minecraft 世界根目录。
        token: 可选的协作取消令牌。

    Returns:
        按稳定顺序排列的目标快照。

    Raises:
        FileNotFoundError: 世界目录不存在或缺少 ``level.dat``。
    """
    world = world_path.expanduser().resolve()
    if not world.is_dir() or not (world / "level.dat").is_file():
        raise FileNotFoundError(f"不是有效 Minecraft 存档: {world}")
    _raise_if_cancelled(token)
    targets = [NbtDocumentTarget("世界 / level.dat", Path("level.dat"), "nbt")]
    targets.extend(_scan_folder(world, "data", "数据", "*.dat", "nbt"))
    _raise_if_cancelled(token)
    targets.extend(_scan_folder(world, "stats", "统计", "*.json", "json"))
    targets.extend(
        _scan_folder(world, "advancements", "进度", "*.json", "json")
    )
    _raise_if_cancelled(token)
    return tuple(targets)


def load_nbt_document(
    world_path: Path,
    target: NbtDocumentTarget,
    token: Optional[CancellationToken] = None,
) -> LoadedNbtDocument:
    """安全读取一个世界相对 NBT 或 JSON 文件。

    Args:
        world_path: 当前 Minecraft 世界根目录。
        target: 已发现或由调用方构造的文档目标。
        token: 可选的协作取消令牌。

    Returns:
        保留 NBT 标签类型的文档快照。

    Raises:
        NbtDocumentPathError: 目标是绝对路径、越界或穿过链接。
        FileNotFoundError: 目标不存在或扩展名与格式不匹配。
        json.JSONDecodeError: JSON 文档内容无效。
    """
    expected_suffix = ".dat" if target.format == "nbt" else ".json"
    path = _resolve_world_file(world_path, target.relative_path, expected_suffix)
    _raise_if_cancelled(token)
    if target.format == "nbt":
        data = nbtlib.load(path)
    else:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    _raise_if_cancelled(token)
    return LoadedNbtDocument(target, data)


def _scan_folder(
    world: Path,
    folder_name: str,
    label: str,
    pattern: str,
    document_format: NbtDocumentFormat,
) -> list[NbtDocumentTarget]:
    folder = world / folder_name
    if not folder.is_dir() or _is_link(folder):
        return []
    return [
        NbtDocumentTarget(
            f"{label} / {path.name}",
            path.relative_to(world),
            document_format,
        )
        for path in sorted(folder.glob(pattern), key=lambda entry: entry.name)
        if path.is_file() and not _is_link(path)
    ]


def _resolve_world_file(
    world_path: Path,
    relative_path: Path,
    suffix: str,
) -> Path:
    if relative_path.is_absolute():
        raise NbtDocumentPathError("NBT 文档必须使用当前存档内的相对路径")
    world = world_path.expanduser().resolve()
    candidate = world / relative_path
    _reject_link_components(world, candidate)
    resolved = candidate.resolve()
    try:
        resolved.relative_to(world)
    except ValueError as error:
        raise NbtDocumentPathError("NBT 文档必须位于当前存档目录内") from error
    if resolved.suffix.lower() != suffix or not resolved.is_file():
        raise FileNotFoundError(f"NBT 文档不存在或类型不匹配: {relative_path}")
    return resolved


def _reject_link_components(world: Path, candidate: Path) -> None:
    try:
        relative = candidate.relative_to(world)
    except ValueError as error:
        raise NbtDocumentPathError("NBT 文档必须位于当前存档目录内") from error
    current = world
    for component in relative.parts:
        current /= component
        if _is_link(current):
            raise NbtDocumentPathError(
                f"NBT 文档路径不能穿过符号链接或 junction: {current}"
            )


def _is_link(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(callable(is_junction) and is_junction())


def _raise_if_cancelled(token: Optional[CancellationToken]) -> None:
    if token is not None:
        token.raise_if_cancelled()


__all__ = [
    "LoadedNbtDocument",
    "NbtDocumentFormat",
    "NbtDocumentPathError",
    "NbtDocumentTarget",
    "find_nbt_documents",
    "load_nbt_document",
]
