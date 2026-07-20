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
        """稳定目标键，用于暂存分组与去重。

        Returns:
            ``chunk:<posix路径>:<x>:<z>`` 形式的唯一键。
        """
        return f"chunk:{self.region_path.as_posix()}:{self.chunk_x}:{self.chunk_z}"


NbtTarget = Union[str, Path, ChunkNbtTarget]


@dataclass(frozen=True)
class NbtChange:
    """一个等待写入存档的 NBT、JSON 或区块变更。

    ``operation`` 由 ``create`` 根据 old/new 推导，调用方勿手写冲突语义。
    """

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
        """按旧/新值推导操作类型并构造不可变变更。

        Args:
            target: 文件路径、玩家 UUID 或区块目标。
            target_label: UI 展示用标签。
            format: 编辑格式（nbt/json/chunk 等）。
            path: NBT 路径部件序列。
            display_path: 人类可读路径字符串。
            old_value: 变更前值；新增时为 None。
            new_value: 变更后值；删除时为 None。

        Returns:
            带有 set/add/delete 操作标记的 ``NbtChange``。
        """
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
        """按目标类型生成分组键。

        Returns:
            ``chunk:`` / ``file:`` / ``player:`` 前缀键。
        """
        if isinstance(self.target, ChunkNbtTarget):
            return self.target.key
        if isinstance(self.target, Path):
            return f"file:{self.target.as_posix()}"
        return f"player:{self.target}"


class NbtStageStore:
    """维护 NBT 暂存区，避免 UI 直接共享可变列表。

    所有权在会话侧；视图只通过本类读写，提交成功后应 ``clear``。
    """

    def __init__(self) -> None:
        """创建空暂存列表。"""
        self._changes: list[NbtChange] = []

    def __len__(self) -> int:
        return len(self._changes)

    def __bool__(self) -> bool:
        return bool(self._changes)

    @property
    def changes(self) -> Tuple[NbtChange, ...]:
        """当前全部暂存变更的不可变快照。"""
        return tuple(self._changes)

    def add(self, change: NbtChange) -> None:
        """追加一条暂存变更。

        Args:
            change: 待写入的 NBT/JSON/区块变更。
        """
        self._changes.append(change)

    def remove(self, index: int) -> Optional[NbtChange]:
        """按索引移除一条暂存变更。

        Args:
            index: 0-based 索引。

        Returns:
            被移除的变更；越界时为 None。
        """
        if index < 0 or index >= len(self._changes):
            return None
        return self._changes.pop(index)

    def clear(self) -> int:
        """清空暂存区。

        Returns:
            清空前的条目数量。
        """
        count = len(self._changes)
        self._changes.clear()
        return count

    def grouped_by_target(self) -> Dict[str, list[Tuple[int, NbtChange]]]:
        """按 ``target_key`` 分组，保留原始索引。

        Returns:
            ``target_key -> [(index, change), ...]`` 的可变字典副本。
        """
        grouped: Dict[str, list[Tuple[int, NbtChange]]] = {}
        for index, change in enumerate(self._changes):
            grouped.setdefault(change.target_key, []).append((index, change))
        return grouped

    def count_by_format(self) -> Dict[NbtEditFormat, int]:
        """统计各编辑格式的暂存条数。

        Returns:
            格式到计数的映射（仅含出现过的格式）。
        """
        counts: Dict[NbtEditFormat, int] = {}
        for change in self._changes:
            counts[change.format] = counts.get(change.format, 0) + 1
        return counts
