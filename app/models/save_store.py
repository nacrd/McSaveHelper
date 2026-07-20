"""UI-independent state for the selected world and recent worlds."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Optional, Tuple

from app.models.save_context import CurrentSaveContext


@dataclass(frozen=True)
class RecentSave:
    path: str
    name: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> Optional["RecentSave"]:
        path = value.get("path")
        if not isinstance(path, str) or not path:
            return None
        name = value.get("name")
        return cls(path=path, name=name if isinstance(name, str) else "")

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "name": self.name}


CurrentSaveSubscriber = Callable[[Optional[CurrentSaveContext]], None]
RecentSavesSubscriber = Callable[[Tuple[RecentSave, ...]], None]


class CurrentSaveStore:
    """Own current-save state and publish immutable snapshots to adapters."""

    MAX_RECENT_SAVES = 5

    def __init__(self) -> None:
        self._current: Optional[CurrentSaveContext] = None
        self._recent: list[RecentSave] = []
        self._current_subscribers: list[CurrentSaveSubscriber] = []
        self._recent_subscribers: list[RecentSavesSubscriber] = []

    @property
    def current(self) -> Optional[CurrentSaveContext]:
        return self._current

    @property
    def current_path(self) -> Optional[str]:
        return self._current.display_path if self._current else None

    @property
    def recent(self) -> Tuple[RecentSave, ...]:
        return tuple(self._recent)

    def subscribe_current(self, callback: CurrentSaveSubscriber) -> None:
        if callback not in self._current_subscribers:
            self._current_subscribers.append(callback)

    def subscribe_recent(self, callback: RecentSavesSubscriber) -> None:
        if callback not in self._recent_subscribers:
            self._recent_subscribers.append(callback)

    def select(self, context: CurrentSaveContext) -> None:
        self._current = context
        for callback in tuple(self._current_subscribers):
            callback(context)

    def clear(self) -> None:
        self._current = None
        for callback in tuple(self._current_subscribers):
            callback(None)

    def replace_recent(
        self,
        saves: Iterable[RecentSave | Mapping[str, object]],
    ) -> None:
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
        selected = RecentSave(path=context.display_path, name=context.name)
        self._recent = [save for save in self._recent if save.path != selected.path]
        self._recent.insert(0, selected)
        del self._recent[self.MAX_RECENT_SAVES:]
        self._publish_recent()

    def remove_recent(self, path: str) -> bool:
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
