"""玩家列表与详情头像请求的不可变生命周期状态。"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class AvatarRequestKind(Enum):
    """玩家页异步头像请求类别。"""

    LIST = "list"
    DETAIL = "detail"


@dataclass(frozen=True)
class PlayerAvatarState:
    """两类头像请求的 generation 与关闭状态。"""

    list_generation: int = 0
    detail_generation: int = 0
    is_closed: bool = False


def begin_avatar_requests(
    state: PlayerAvatarState,
    kind: AvatarRequestKind,
) -> PlayerAvatarState:
    """推进指定请求类别，保持另一类请求身份不变。"""
    if state.is_closed:
        return state
    if kind is AvatarRequestKind.LIST:
        return replace(state, list_generation=state.list_generation + 1)
    return replace(state, detail_generation=state.detail_generation + 1)


def avatar_generation(
    state: PlayerAvatarState,
    kind: AvatarRequestKind,
) -> int:
    """返回指定请求类别的当前 generation。"""
    if kind is AvatarRequestKind.LIST:
        return state.list_generation
    return state.detail_generation


def owns_avatar_request(
    state: PlayerAvatarState,
    kind: AvatarRequestKind,
    generation: int,
) -> bool:
    """判断回调是否仍属于未关闭的最新请求。"""
    return (
        not state.is_closed
        and generation == avatar_generation(state, kind)
    )


def close_avatar_requests(state: PlayerAvatarState) -> PlayerAvatarState:
    """关闭状态并同时使列表与详情请求失效。"""
    if state.is_closed:
        return state
    return PlayerAvatarState(
        list_generation=state.list_generation + 1,
        detail_generation=state.detail_generation + 1,
        is_closed=True,
    )


__all__ = [
    "AvatarRequestKind",
    "PlayerAvatarState",
    "avatar_generation",
    "begin_avatar_requests",
    "close_avatar_requests",
    "owns_avatar_request",
]
