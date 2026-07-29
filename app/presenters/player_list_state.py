"""玩家列表分页/虚拟化用的不可变 ViewState。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence


@dataclass(frozen=True)
class PlayerListItemState:
    """列表中一行玩家的投影数据。"""

    uuid: str
    display_name: str


@dataclass(frozen=True)
class PlayerListViewState:
    """一页玩家列表快照。"""

    items: tuple[PlayerListItemState, ...]
    total_count: int
    page_index: int
    page_size: int
    query: str

    @property
    def page_count(self) -> int:
        """总页数（至少 1）。"""
        if self.page_size < 1:
            return 1
        return max(1, (self.total_count + self.page_size - 1) // self.page_size)


def _ref_fields(ref: Any) -> tuple[str, str, str]:
    uuid = str(
        getattr(ref, "uuid_norm", None)
        or getattr(ref, "uuid", None)
        or ""
    )
    uuid_hyphen = str(getattr(ref, "uuid_hyphen", None) or uuid)
    display = str(
        getattr(ref, "display_name", None)
        or getattr(ref, "name", None)
        or uuid_hyphen
        or uuid
        or "?"
    )
    return uuid, uuid_hyphen, display


def build_player_list_state(
    refs: Sequence[Any],
    *,
    query: str = "",
    page_index: int = 0,
    page_size: int = 40,
) -> PlayerListViewState:
    """过滤并分页构造玩家列表 ViewState。

    Args:
        refs: 玩家引用（需提供 uuid_norm / display_name 或兼容属性）。
        query: 名称/UUID 子串过滤（大小写不敏感）。
        page_index: 从 0 开始的页码。
        page_size: 每页条数。
    """
    needle = (query or "").strip().lower()
    filtered: list[tuple[str, str]] = []
    for ref in refs:
        uuid, uuid_hyphen, display = _ref_fields(ref)
        haystack = f"{display} {uuid} {uuid_hyphen}".lower()
        if needle and needle not in haystack:
            continue
        filtered.append((uuid, display))
    size = max(1, int(page_size))
    total = len(filtered)
    page_count = max(1, (total + size - 1) // size) if total else 1
    page = max(0, min(int(page_index), page_count - 1))
    start = page * size
    window = filtered[start: start + size]
    items = tuple(
        PlayerListItemState(uuid=uuid, display_name=display)
        for uuid, display in window
    )
    return PlayerListViewState(
        items=items,
        total_count=total,
        page_index=page,
        page_size=size,
        query=query or "",
    )


__all__ = [
    "PlayerListItemState",
    "PlayerListViewState",
    "build_player_list_state",
]
