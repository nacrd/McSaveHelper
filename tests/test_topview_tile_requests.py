from dataclasses import dataclass
from typing import List, Optional, Set, Tuple

from app.controllers.topview_tile_requests import TopviewTileRequestCoordinator
from app.services.region_map.types import TopviewTileState


RegionCoord = Tuple[int, int]


@dataclass(frozen=True)
class _RequestCall:
    coords: Tuple[RegionCoord, ...]
    tile_size: int
    force: bool
    priority: bool


class _TileService:
    def __init__(self, accept_limit: Optional[int] = None) -> None:
        self.accept_limit = accept_limit
        self.cached_sizes: dict[RegionCoord, int] = {}
        self.pending_sizes: dict[RegionCoord, int] = {}
        self.calls: list[_RequestCall] = []

    def get_topview_tile_state(self, coord: RegionCoord) -> TopviewTileState:
        return TopviewTileState(
            generation=1,
            available_size=self.cached_sizes.get(coord, 0),
            requested_size=self.pending_sizes.get(coord, 0),
        )

    def request_topview_tiles(
        self,
        coords: List[RegionCoord],
        tile_size: Optional[int] = None,
        *,
        force: bool = False,
        priority: bool = False,
    ) -> Set[RegionCoord]:
        size = int(tile_size or 32)
        self.calls.append(_RequestCall(tuple(coords), size, force, priority))
        accepted: Set[RegionCoord] = set()
        for coord in coords:
            if self.cached_sizes.get(coord, 0) >= size:
                continue
            if self.accept_limit is not None and len(accepted) >= self.accept_limit:
                break
            self.pending_sizes[coord] = max(size, self.pending_sizes.get(coord, 0))
            accepted.add(coord)
        return accepted

    def finish(self, coord: RegionCoord, size: int) -> None:
        self.pending_sizes.pop(coord, None)
        self.cached_sizes[coord] = size


def test_visible_requests_progress_from_preview_to_ordinary_lod() -> None:
    service = _TileService()
    coordinator = TopviewTileRequestCoordinator(service)
    coords = [(-1, 0), (0, 0), (1, 0)]

    coordinator.request_visible(
        coords,
        visible_regions=coords,
        scale=8.0,
        center=(0, 0),
    )

    assert service.calls[-1] == _RequestCall(
        tuple([(0, 0), (-1, 0), (1, 0)]),
        16,
        False,
        False,
    )
    for coord in coords:
        service.finish(coord, 16)
        coordinator.on_tile_ready(coord)

    coordinator.request_visible(
        coords,
        visible_regions=coords,
        scale=8.0,
        center=(0, 0),
    )

    assert service.calls[-1].tile_size == 32
    for coord in coords:
        service.finish(coord, 32)
        coordinator.on_tile_ready(coord)

    coordinator.request_visible(
        coords,
        visible_regions=coords,
        scale=8.0,
        center=(0, 0),
    )

    assert service.calls[-1].tile_size == 256
    assert 512 not in {call.tile_size for call in service.calls}


def test_intermediate_tile_callback_keeps_visible_request_ledger() -> None:
    service = _TileService()
    coordinator = TopviewTileRequestCoordinator(service)
    coord = (0, 0)

    coordinator.request_visible(
        [coord],
        visible_regions=[coord],
        scale=1.0,
        center=coord,
    )

    coordinator.on_tile_ready(coord)
    assert coordinator.requested_sizes == {coord: 16}

    service.finish(coord, 16)
    coordinator.on_tile_ready(coord)
    assert coordinator.requested_sizes == {}


def test_leaf_lod_upgrades_only_selected_or_center_region() -> None:
    service = _TileService()
    coordinator = TopviewTileRequestCoordinator(service)
    coords = [(-1, 0), (0, 0), (1, 0)]
    service.cached_sizes.update({coord: 256 for coord in coords})

    accepted = coordinator.request_selected_detail(
        scale=8.0,
        selected=None,
        center=(0, 0),
        available_regions=coords,
        enabled=True,
    )

    assert accepted == {(0, 0)}
    assert service.calls[-1] == _RequestCall(((0, 0),), 512, True, True)

    service.finish((0, 0), 512)
    coordinator.request_selected_detail(
        scale=8.0,
        selected=(1, 0),
        center=(0, 0),
        available_regions=coords,
        enabled=True,
    )

    assert service.calls[-1] == _RequestCall(((1, 0),), 512, True, True)


def test_non_leaf_selected_detail_includes_existing_neighbor_regions() -> None:
    service = _TileService()
    coordinator = TopviewTileRequestCoordinator(service)
    available = {(0, 0), (1, 0), (0, 1)}

    coordinator.request_selected_detail(
        scale=2.2,
        selected=(0, 0),
        center=(0, 0),
        available_regions=available,
        enabled=True,
    )

    assert service.calls[-1].tile_size == 256
    assert set(service.calls[-1].coords) == available
    assert service.calls[-1].priority is True


def test_rejected_visible_tail_stays_deferred_and_evicted_ledger_retries() -> None:
    service = _TileService(accept_limit=1)
    coordinator = TopviewTileRequestCoordinator(service)
    coords = [(0, 0), (1, 0), (2, 0)]

    coordinator.request_visible(
        coords,
        visible_regions=coords,
        scale=1.0,
        center=(0, 0),
    )

    assert coordinator.requested_sizes == {(0, 0): 16}
    assert coordinator.has_deferred_requests is True
    assert coordinator.on_tile_ready((99, 99)) is True

    service.pending_sizes.clear()
    coordinator.request_visible(
        coords,
        visible_regions=coords,
        scale=1.0,
        center=(0, 0),
    )

    assert len(service.calls) == 2
    assert coordinator.requested_sizes == {(0, 0): 16}


def test_visible_lod_switches_to_leaf_target_only_at_scale_eight() -> None:
    coordinator = TopviewTileRequestCoordinator(_TileService())

    assert coordinator.visible_tile_size(7.99) == 256
    assert coordinator.visible_tile_size(8.0) == 512
    assert coordinator.visible_base_tile_size(8.0) == 256
