"""Shared host contract for Explorer tab mixins."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

import flet as ft

from app.models.nbt_edit import (
    ChunkNbtTarget,
    NbtEditFormat,
    NbtStageStore,
    NbtTarget,
)
from app.services.region_map_service import RegionMapService
from app.controllers.map_controller import MapController
from core.omni.world_session import WorldSession

if TYPE_CHECKING:
    from app.application import Application


class ExplorerMixinHost:
    """Declare state and cross-tab operations supplied by ``ExplorerView``.

    Tab mixins stay independently importable, while their dependencies remain
    visible to static analysis instead of being implicit in the final multiple
    inheritance composition.
    """

    app: "Application"
    world_session: Optional[WorldSession]
    current_uuid: Optional[str]

    _current_player_data: Optional[Any]
    _current_nbt_target: Optional[NbtTarget]
    _current_nbt_label: str
    _current_edit_format: NbtEditFormat
    _current_chunk_target: Optional[ChunkNbtTarget]
    _current_dimension: str
    _dimension_region_dirs: Dict[str, str]
    _selected_region_coord: Optional[Tuple[int, int]]

    _nbt_stage_store: NbtStageStore
    _map_service: RegionMapService
    _map_controller: MapController

    _tab_world_info: ft.Container
    _tab_player: ft.Container
    _tab_region: ft.Container
    _tab_stats: ft.Container
    _tab_nbt: ft.Container

    # Controls built by the NBT tab and reused by player/region tabs.
    _nbt_target_label: ft.Text
    _nbt_tree: Any
    _region_file_field: ft.TextField
    _chunk_x_field: ft.TextField
    _chunk_z_field: ft.TextField
    _world_x_field: ft.TextField
    _world_z_field: ft.TextField

    def _load_player_data(self, uuid: str) -> None:
        raise NotImplementedError

    def _update_nbt_stage_status(self) -> None:
        raise NotImplementedError

    def _switch_tab(self, index: int) -> None:
        raise NotImplementedError

    def _load_chunk_nbt(self, event: Any = None) -> None:
        raise NotImplementedError

    def _load_world(self, path: Any = None) -> None:
        raise NotImplementedError

    @staticmethod
    def _tag_display_value(value: Any) -> str:
        raise NotImplementedError

    @staticmethod
    def _coerce_like_tag(raw: str, original: Any) -> Any:
        raise NotImplementedError

    @staticmethod
    def _world_coords_to_region_chunk(
        world_x: int,
        world_z: int,
    ) -> Tuple[int, int, int, int]:
        raise NotImplementedError
