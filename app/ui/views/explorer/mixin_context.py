"""Shared host contract for Explorer tab mixins."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional, Protocol, Tuple

import flet as ft

from app.models.nbt_edit import NbtStageStore
from app.presenters.nbt_view_state import NbtViewState
from app.presenters.quick_backup_state import QuickBackupState
from app.presenters.stats_view_state import StatsAnalysisState
from app.services.execution_runtime import OperationScope
from app.services.region_map import RegionMapService
from app.controllers.map_controller import MapController
from app.controllers.region_delete_controller import RegionDeleteController
from app.ui.feature_context import (
    FeatureDialogPort,
    FeatureFileDialogPort,
    FeatureMapPort,
    FeaturePagePort,
    FeatureProgressPort,
    FeatureRuntimePort,
    FeatureTranslationPort,
)
from core.omni.world_session import WorldSession

if TYPE_CHECKING:
    from app.core.save_context_manager import SaveContextManager
    from app.core.view_manager import ViewManager
    from app.services.backup_service import BackupService
    from app.services.cache_registry import CacheRegistry
    from app.services.item_service import ItemService
    from app.services.texture_service import TextureService
    from app.services.ui_delivery import UiDeliveryPort
    from app.services.world_repository import WorldRepository
    from app.services.world_stats_service import WorldStatsService
    from app.services.world_transaction import WorldTransactionService


class ExplorerHost(
    FeaturePagePort,
    FeatureTranslationPort,
    FeatureDialogPort,
    FeatureFileDialogPort,
    FeatureProgressPort,
    FeatureRuntimePort,
    FeatureMapPort,
    Protocol,
):
    """Explicit UI and service ports consumed across Explorer tabs."""

    @property
    def current_save_path(self) -> Optional[str]:
        """Return the selected world path, if any."""
        ...

    @property
    def save_context_manager(self) -> SaveContextManager:
        """Return the application save-context coordinator."""
        ...

    @property
    def view_manager(self) -> ViewManager:
        """Return the shell view coordinator."""
        ...

    @property
    def backup(self) -> BackupService:
        """Return the managed backup service."""
        ...

    @property
    def world_transactions(self) -> WorldTransactionService:
        """Return the shared world transaction service."""
        ...

    @property
    def world_repository(self) -> WorldRepository:
        """Return the shared world read repository."""
        ...

    @property
    def world_stats(self) -> WorldStatsService:
        """Return the world statistics service."""
        ...

    @property
    def ui_delivery(self) -> UiDeliveryPort:
        """Return the guarded UI delivery port."""
        ...

    @property
    def cache_registry(self) -> CacheRegistry:
        """Return the shared cache registry."""
        ...

    @property
    def item(self) -> ItemService:
        """Return the item metadata service."""
        ...

    @property
    def texture(self) -> TextureService:
        """Return the texture service."""
        ...


class ExplorerMixinHost:
    """Declare state and cross-tab operations supplied by ``ExplorerView``.

    Tab mixins stay independently importable, while their dependencies remain
    visible to static analysis instead of being implicit in the final multiple
    inheritance composition.
    """

    app: ExplorerHost
    world_session: Optional[WorldSession]
    current_uuid: Optional[str]

    _current_player_data: Optional[Any]
    _nbt_view_state: NbtViewState
    _current_dimension: str
    _dimension_region_dirs: Dict[str, str]
    _selected_region_coord: Optional[Tuple[int, int]]
    _tabs_built: list[bool]
    _task_scope: OperationScope
    _world_load_generation: int
    _quick_backup_state: QuickBackupState
    _stats_analysis_state: StatsAnalysisState
    _marker_busy: bool

    _nbt_stage_store: NbtStageStore
    _map_service: RegionMapService
    _map_controller: MapController
    _region_delete_controller: RegionDeleteController

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

    @property
    def _t(self) -> Any:
        """返回应用翻译回调。"""
        return self.app.translate

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
