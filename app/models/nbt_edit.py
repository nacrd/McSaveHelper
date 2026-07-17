"""NBT 编辑会话使用的纯数据模型。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Literal, Optional, Tuple, Union


NbtPathPart = Union[str, int]
NbtPath = Tuple[NbtPathPart, ...]
NbtEditFormat = Literal["nbt", "json", "chunk", "chunk_readonly"]
NbtOperation = Literal["set", "add", "delete"]


@dataclass(frozen=True)
class ChunkNbtTarget:
    """一个可写区块及其当前完整 NBT 数据。"""

    region_path: Path
    chunk_x: int
    chunk_z: int
    data: Any

    @property
    def key(self) -> str:
        return f"chunk:{self.region_path.as_posix()}:{self.chunk_x}:{self.chunk_z}"


NbtTarget = Union[str, Path, ChunkNbtTarget]


@dataclass(frozen=True)
class NbtChange:
    """一个等待写入存档的 NBT、JSON 或区块变更。"""

    target: NbtTarget
    target_label: str
    format: NbtEditFormat
    operation: NbtOperation
    path: NbtPath
    display_path: str
    old_value: Any
    new_value: Any

    @classmethod
    def create(
        cls,
        *,
        target: NbtTarget,
        target_label: str,
        format: NbtEditFormat,
        path: Iterable[NbtPathPart],
        display_path: str,
        old_value: Any,
        new_value: Any,
    ) -> "NbtChange":
        if new_value is None:
            operation: NbtOperation = "delete"
        elif old_value is None:
            operation = "add"
        else:
            operation = "set"
        return cls(
            target=target,
            target_label=target_label,
            format=format,
            operation=operation,
            path=tuple(path),
            display_path=display_path,
            old_value=old_value,
            new_value=new_value,
        )

    @property
    def target_key(self) -> str:
        if isinstance(self.target, ChunkNbtTarget):
            return self.target.key
        if isinstance(self.target, Path):
            return f"file:{self.target.as_posix()}"
        return f"player:{self.target}"


class NbtStageStore:
    """维护 NBT 暂存区，避免 UI 直接共享可变列表。"""

    def __init__(self) -> None:
        self._changes: list[NbtChange] = []

    def __len__(self) -> int:
        return len(self._changes)

    def __bool__(self) -> bool:
        return bool(self._changes)

    @property
    def changes(self) -> Tuple[NbtChange, ...]:
        return tuple(self._changes)

    def add(self, change: NbtChange) -> None:
        self._changes.append(change)

    def remove(self, index: int) -> Optional[NbtChange]:
        if index < 0 or index >= len(self._changes):
            return None
        return self._changes.pop(index)

    def clear(self) -> int:
        count = len(self._changes)
        self._changes.clear()
        return count

    def grouped_by_target(self) -> Dict[str, list[Tuple[int, NbtChange]]]:
        grouped: Dict[str, list[Tuple[int, NbtChange]]] = {}
        for index, change in enumerate(self._changes):
            grouped.setdefault(change.target_key, []).append((index, change))
        return grouped

    def count_by_format(self) -> Dict[NbtEditFormat, int]:
        counts: Dict[NbtEditFormat, int] = {}
        for change in self._changes:
            counts[change.format] = counts.get(change.format, 0) + 1
        return counts
