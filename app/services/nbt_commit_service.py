"""将不可变 NBT 变更快照应用到一个世界写事务。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from app.models.nbt_edit import ChunkNbtTarget, NbtChange
from app.services.execution_runtime import CancellationToken
from core.omni.world_session import WorldSession


@dataclass(frozen=True)
class NbtCommitResult:
    """一次 NBT 提交的不可变业务结果。"""

    world_path: Path
    requested_changes: int
    queued_operations: int
    committed: bool


def commit_nbt_changes(
    session: WorldSession,
    changes: Sequence[NbtChange],
    token: CancellationToken,
) -> NbtCommitResult:
    """在后台线程中重放变更并通过世界事务提交。

    Args:
        session: 提供读快照和共享世界写事务端口的会话。
        changes: UI 线程创建的不可变暂存快照。
        token: 运行时协作取消标记。

    Returns:
        提交世界、变更数、队列数与事务结果。
    """
    token.raise_if_cancelled()
    commit_session = session.new_action_session()
    chunk_changes, normal_changes = _partition_changes(changes)
    _queue_normal_changes(commit_session, normal_changes, token)
    _queue_chunk_changes(commit_session, chunk_changes, token)
    token.raise_if_cancelled()

    queued = commit_session.get_queue_size()
    committed = commit_session.commit(
        backup=True,
        cancel_check=lambda: token.is_cancelled,
    )
    if not committed:
        token.raise_if_cancelled()
    return NbtCommitResult(
        world_path=commit_session.world_path,
        requested_changes=len(changes),
        queued_operations=queued,
        committed=committed,
    )


def _partition_changes(
    changes: Sequence[NbtChange],
) -> Tuple[Dict[str, Tuple[ChunkNbtTarget, List[NbtChange]]], List[NbtChange]]:
    """按区块目标与普通文件目标拆分变更。"""
    chunk_changes: Dict[str, Tuple[ChunkNbtTarget, List[NbtChange]]] = {}
    normal_changes: List[NbtChange] = []
    for change in changes:
        if isinstance(change.target, ChunkNbtTarget):
            entry = chunk_changes.setdefault(
                change.target.key,
                (change.target, []),
            )
            entry[1].append(change)
        else:
            normal_changes.append(change)
    return chunk_changes, normal_changes


def _queue_normal_changes(
    session: WorldSession,
    changes: Sequence[NbtChange],
    token: CancellationToken,
) -> None:
    """把 NBT/JSON 文件变更加入动作会话。"""
    for change in changes:
        token.raise_if_cancelled()
        target = change.target
        if isinstance(target, ChunkNbtTarget):
            raise ValueError("区块变更不能进入普通 NBT/JSON 提交队列")
        path = list(change.path)
        if change.format == "json":
            session.queue_modify_json(
                target,
                path,
                change.new_value,
                operation=change.operation,
            )
        else:
            session.queue_modify_nbt(
                target,
                path,
                change.new_value,
                operation=change.operation,
            )


def _queue_chunk_changes(
    session: WorldSession,
    chunk_changes: Dict[
        str,
        Tuple[ChunkNbtTarget, List[NbtChange]],
    ],
    token: CancellationToken,
) -> None:
    """从磁盘重载每个区块，重放快照并加入完整区块写入。"""
    for target, target_changes in chunk_changes.values():
        token.raise_if_cancelled()
        loaded = session.load_chunk_nbt(
            target.region_path,
            target.chunk_x,
            target.chunk_z,
        )
        if loaded is None:
            raise ValueError(f"无法重新加载待提交区块: {target.key}")
        chunk_data = loaded[0]
        for change in target_changes:
            token.raise_if_cancelled()
            _apply_change(chunk_data, change)
        session.queue_modify_chunk(
            target.region_path,
            target.chunk_x,
            target.chunk_z,
            chunk_data,
        )


def _apply_change(data: Any, change: NbtChange) -> None:
    """把一个已验证路径的变更应用到内存标签树。"""
    if not change.path:
        raise ValueError("区块变更路径不能为空")
    node = data
    for part in change.path[:-1]:
        node = node[part]
    key = change.path[-1]
    if change.operation == "delete":
        del node[key]
    elif change.operation == "add" and isinstance(key, int):
        node.insert(key, change.new_value)
    else:
        node[key] = change.new_value


__all__ = ["NbtCommitResult", "commit_nbt_changes"]
