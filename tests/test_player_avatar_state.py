"""玩家页头像请求所有权状态。"""
from app.presenters.player_avatar_state import (
    AvatarRequestKind,
    PlayerAvatarState,
    avatar_generation,
    begin_avatar_requests,
    close_avatar_requests,
    owns_avatar_request,
)


def test_list_and_detail_avatar_generations_are_independent() -> None:
    state = PlayerAvatarState()
    state = begin_avatar_requests(state, AvatarRequestKind.LIST)
    list_generation = avatar_generation(state, AvatarRequestKind.LIST)
    state = begin_avatar_requests(state, AvatarRequestKind.DETAIL)
    detail_generation = avatar_generation(state, AvatarRequestKind.DETAIL)

    assert owns_avatar_request(
        state,
        AvatarRequestKind.LIST,
        list_generation,
    )
    assert owns_avatar_request(
        state,
        AvatarRequestKind.DETAIL,
        detail_generation,
    )

    next_state = begin_avatar_requests(state, AvatarRequestKind.LIST)

    assert not owns_avatar_request(
        next_state,
        AvatarRequestKind.LIST,
        list_generation,
    )
    assert owns_avatar_request(
        next_state,
        AvatarRequestKind.DETAIL,
        detail_generation,
    )


def test_close_invalidates_both_avatar_request_kinds() -> None:
    state = begin_avatar_requests(
        PlayerAvatarState(),
        AvatarRequestKind.LIST,
    )
    state = begin_avatar_requests(state, AvatarRequestKind.DETAIL)
    list_generation = avatar_generation(state, AvatarRequestKind.LIST)
    detail_generation = avatar_generation(state, AvatarRequestKind.DETAIL)

    closed = close_avatar_requests(state)

    assert closed.is_closed is True
    assert not owns_avatar_request(
        closed,
        AvatarRequestKind.LIST,
        list_generation,
    )
    assert not owns_avatar_request(
        closed,
        AvatarRequestKind.DETAIL,
        detail_generation,
    )
    assert begin_avatar_requests(closed, AvatarRequestKind.LIST) is closed
    assert close_avatar_requests(closed) is closed
