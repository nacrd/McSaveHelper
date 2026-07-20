"""UI-independent state for the selected world and recent worlds."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Optional, Tuple

from app.models.save_context import CurrentSaveContext


@dataclass(frozen=True)
class RecentSave:
    """最近打开过的存档条目（路径 + 展示名）。"""

    path: str
    name: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> Optional["RecentSave"]:
        """从配置映射解析条目。

        Args:
            value: 至少含非空 ``path`` 字符串的映射。

        Returns:
            有效条目；路径缺失或非字符串时为 None。
        """
        path = value.get("path")
        if not isinstance(path, str) or not path:
            return None
        name = value.get("name")
        return cls(path=path, name=name if isinstance(name, str) else "")

    def to_dict(self) -> dict[str, str]:
        """序列化为可写入配置的字典。

        Returns:
            含 ``path`` 与 ``name`` 的字符串字典。
        """
        return {"path": self.path, "name": self.name}


CurrentSaveSubscriber = Callable[[Optional[CurrentSaveContext]], None]
RecentSavesSubscriber = Callable[[Tuple[RecentSave, ...]], None]


class CurrentSaveStore:
    """拥有当前存档状态，并向适配器发布不可变快照。

    不负责校验 level.dat 或写盘；由 SaveContextManager 编排。
    订阅回调在调用方线程同步触发，回调应短且勿重入修改订阅列表语义。
    """

    MAX_RECENT_SAVES = 5

    def __init__(self) -> None:
        """创建空的当前/最近存档状态与订阅表。"""
        self._current: Optional[CurrentSaveContext] = None
        self._recent: list[RecentSave] = []
        self._current_subscribers: list[CurrentSaveSubscriber] = []
        self._recent_subscribers: list[RecentSavesSubscriber] = []

    @property
    def current(self) -> Optional[CurrentSaveContext]:
        """当前选中的存档上下文；未选择时为 None。"""
        return self._current

    @property
    def current_path(self) -> Optional[str]:
        """当前存档的展示路径字符串；未选择时为 None。"""
        return self._current.display_path if self._current else None

    @property
    def recent(self) -> Tuple[RecentSave, ...]:
        """最近存档的不可变快照（最多 ``MAX_RECENT_SAVES`` 条）。"""
        return tuple(self._recent)

    def subscribe_current(self, callback: CurrentSaveSubscriber) -> None:
        """订阅当前存档变化（同一回调只登记一次）。

        Args:
            callback: 收到 ``CurrentSaveContext | None`` 的同步回调。
        """
        if callback not in self._current_subscribers:
            self._current_subscribers.append(callback)

    def subscribe_recent(self, callback: RecentSavesSubscriber) -> None:
        """订阅最近存档列表变化（同一回调只登记一次）。

        Args:
            callback: 收到 ``tuple[RecentSave, ...]`` 快照的同步回调。
        """
        if callback not in self._recent_subscribers:
            self._recent_subscribers.append(callback)

    def select(self, context: CurrentSaveContext) -> None:
        """设置当前存档并通知订阅者。

        Args:
            context: 新的当前存档上下文（调用方保证有效性）。
        """
        self._current = context
        for callback in tuple(self._current_subscribers):
            callback(context)

    def clear(self) -> None:
        """清空当前存档并通知订阅者 ``None``。"""
        self._current = None
        for callback in tuple(self._current_subscribers):
            callback(None)

    def replace_recent(
        self,
        saves: Iterable[RecentSave | Mapping[str, object]],
    ) -> None:
        """用外部列表整体替换最近存档（去重并截断）。

        Args:
            saves: ``RecentSave`` 或可解析映射的可迭代序列。
        """
        normalized: list[RecentSave] = []
        seen_paths: set[str] = set()
        for value in saves:
            save = value if isinstance(value, RecentSave) else RecentSave.from_mapping(value)
            if save is None or save.path in seen_paths:
                continue
            normalized.append(save)
            seen_paths.add(save.path)
            if len(normalized) == self.MAX_RECENT_SAVES:
                break
        self._recent = normalized
        self._publish_recent()

    def remember(self, context: CurrentSaveContext) -> None:
        """将选中存档置顶写入最近列表。

        Args:
            context: 刚选中的存档上下文。
        """
        selected = RecentSave(path=context.display_path, name=context.name)
        self._recent = [save for save in self._recent if save.path != selected.path]
        self._recent.insert(0, selected)
        del self._recent[self.MAX_RECENT_SAVES:]
        self._publish_recent()

    def remove_recent(self, path: str) -> bool:
        """从最近列表移除指定路径。

        Args:
            path: 要移除的存档路径。

        Returns:
            是否实际移除了条目。
        """
        remaining = [save for save in self._recent if save.path != path]
        if len(remaining) == len(self._recent):
            return False
        self._recent = remaining
        self._publish_recent()
        return True

    def _publish_recent(self) -> None:
        snapshot = self.recent
        for callback in tuple(self._recent_subscribers):
            callback(snapshot)
