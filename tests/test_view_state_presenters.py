"""Immutable ViewState presenters for map/player/stats."""
from __future__ import annotations

from types import SimpleNamespace

from app.presenters.map_viewport_state import (
    decide_map_rebuild,
    snapshot_map_view_state,
)
from app.presenters.player_list_state import build_player_list_state
from app.presenters.stats_view_state import build_stats_view_state
from app.services.world_stats_service import (
    PLAYER_SORT_NAME,
    WorldStatistics,
)
from core.mca.map_models import MapViewState


def test_map_rebuild_decision_detects_camera_and_generation() -> None:
    state = MapViewState(center_x=10.0, center_z=20.0, scale=1.0, generation=1)
    first = decide_map_rebuild(None, state)
    assert first.should_rebuild is True
    assert first.reason == "initial"
    same = decide_map_rebuild(first.snapshot, state)
    assert same.should_rebuild is False
    state.center_x = 11.0
    moved = decide_map_rebuild(first.snapshot, state)
    assert moved.should_rebuild is True
    assert moved.reason == "camera"
    state.generation = 2
    gen = decide_map_rebuild(moved.snapshot, state)
    assert gen.reason == "generation"
    snap = snapshot_map_view_state(state)
    assert snap.generation == 2


def test_player_list_state_filters_and_pages() -> None:
    refs = [
        SimpleNamespace(
            uuid_norm="aaa",
            display_name="Alex",
            uuid_hyphen="aaa",
        ),
        SimpleNamespace(
            uuid_norm="bbb",
            display_name="Steve",
            uuid_hyphen="bbb",
        ),
        SimpleNamespace(
            uuid_norm="ccc",
            display_name="Bob",
            uuid_hyphen="ccc",
        ),
    ]
    page = build_player_list_state(refs, query="e", page_index=0, page_size=1)
    assert page.total_count == 2  # Alex, Steve
    assert page.page_count == 2
    assert len(page.items) == 1
    assert page.items[0].display_name in {"Alex", "Steve"}
    by_hyphen = build_player_list_state(
        refs,
        query="bbb",
        page_index=0,
        page_size=10,
    )
    assert by_hyphen.total_count == 1
    assert by_hyphen.items[0].uuid == "bbb"


def test_stats_view_state_from_empty_statistics() -> None:
    stats = WorldStatistics()
    view = build_stats_view_state(stats, player_sort_key=PLAYER_SORT_NAME)
    assert view.total_regions == 0
    assert view.players == ()
    assert any(line.startswith("regions=") for line in view.summary_lines)
