"""地图会话控制器。

控制器承接 Explorer 与地图服务之间的状态协调，保持 Flet 视图只处理
输入和呈现。设计上对应 Xaero 的 ``MapWorld -> MapDimension`` 会话层：
每个维度保存自己的镜头/样式状态，切换维度时旧状态不会污染新维度。
"""
from __future__ import annotations

import copy
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

from app.services.map_marker_service import MapMarkerService
from core.mca.map_models import (
    MapDimension,
    MapMarker,
    MapViewState,
)
from core.mca.map_search import MapSearchResult, parse_map_query


DimensionLike = MapDimension | Mapping[str, Any]
StateCallback = Callable[[MapViewState], None]


class MapController:
    """管理一个存档地图会话的维度、图层、标记和搜索。"""

    def __init__(
        self,
        marker_service: Optional[MapMarkerService] = None,
        on_state_changed: Optional[StateCallback] = None,
    ) -> None:
        self._marker_service = marker_service or MapMarkerService()
        self._on_state_changed = on_state_changed
        self._world_path: Optional[Path] = None
        self._dimensions: dict[str, MapDimension] = {}
        self._states: dict[str, MapViewState] = {}
        self._state = MapViewState()
        self._markers: list[MapMarker] = []

    @property
    def state(self) -> MapViewState:
        """返回当前可变状态；调用方不应替换其内部图层对象。"""
        return self._state

    @property
    def world_path(self) -> Optional[Path]:
        return self._world_path

    @property
    def dimensions(self) -> tuple[MapDimension, ...]:
        return tuple(self._dimensions.values())

    @property
    def current_dimension(self) -> Optional[MapDimension]:
        return self._dimensions.get(self._state.dimension_id)

    def bind_world(
        self,
        world_path: Path | str,
        dimensions: Iterable[DimensionLike],
    ) -> MapViewState:
        """绑定存档和维度目录，开始一个新的地图会话。"""
        self._world_path = Path(world_path).expanduser().resolve()
        parsed: dict[str, MapDimension] = {}
        for item in dimensions:
            dimension = self._coerce_dimension(item)
            parsed[dimension.id] = dimension
        self._dimensions = dict(sorted(parsed.items(), key=lambda pair: pair[0]))
        self._states.clear()
        dimension_id = (
            self._state.dimension_id
            if self._state.dimension_id in self._dimensions
            else next(iter(self._dimensions), "overworld")
        )
        self._state = MapViewState(dimension_id=dimension_id)
        self._states[dimension_id] = self._state
        self._load_markers()
        self._notify()
        return self._state

    def switch_dimension(self, dimension_id: str) -> MapViewState:
        """切换维度并按 coordinate scale 保持相同的世界锚点。"""
        target = self._dimensions.get(str(dimension_id))
        if target is None:
            raise KeyError(f"未找到维度: {dimension_id}")
        current = self.current_dimension
        if target.id == self._state.dimension_id:
            return self._state

        self._states[self._state.dimension_id] = self._state
        saved = self._states.get(target.id)
        if saved is not None:
            self._state = saved
        else:
            ratio = (
                current.coordinate_scale / target.coordinate_scale
                if current is not None
                else 1.0
            )
            self._state = copy.deepcopy(self._state)
            self._state.switch_dimension(target, ratio)
            self._states[target.id] = self._state
        self._load_markers()
        self._notify()
        return self._state

    def set_style(self, style: str) -> MapViewState:
        self._state.set_style(style)
        self._notify()
        return self._state

    def update_camera(self, center_x: float, center_z: float, scale: float) -> None:
        """Store the current dimension camera before a view or dimension swap."""
        self._state.center_x = float(center_x)
        self._state.center_z = float(center_z)
        self._state.scale = max(0.0001, float(scale))
        self._states[self._state.dimension_id] = self._state

    def toggle_layer(self, layer: str, value: Optional[bool] = None) -> bool:
        """切换一个可见图层并返回新值。"""
        aliases = {
            "grid": "show_grid",
            "coordinates": "show_coordinates",
            "markers": "show_markers",
            "empty": "show_empty_regions",
            "show_grid": "show_grid",
            "show_coordinates": "show_coordinates",
            "show_markers": "show_markers",
            "show_empty_regions": "show_empty_regions",
        }
        field_name = aliases.get(layer)
        if field_name is None:
            raise KeyError(f"未知地图图层: {layer}")
        current = bool(getattr(self._state.layers, field_name))
        new_value = (not current) if value is None else bool(value)
        setattr(self._state.layers, field_name, new_value)
        self._state.generation += 1
        self._notify()
        return new_value

    def markers(self, include_disabled: bool = False) -> list[MapMarker]:
        """返回当前维度标记副本。"""
        if self._world_path is None:
            values = self._markers
        else:
            values = self._marker_service.list(
                self._world_path,
                self._state.dimension_id,
                include_disabled=include_disabled,
            )
        return [MapMarker.from_dict(marker.to_dict()) for marker in values]

    def upsert_marker(
        self,
        name: str,
        x: int,
        z: int,
        *,
        y: int = 0,
        marker_id: Optional[str] = None,
        color: str = "#FFD54F",
        group: str = "default",
        icon: str = "pin",
    ) -> MapMarker:
        """在当前维度创建或替换一个用户标记。"""
        marker = MapMarker(
            id=marker_id or uuid.uuid4().hex,
            name=name.strip(),
            x=int(x),
            y=int(y),
            z=int(z),
            dimension_id=self._state.dimension_id,
            color=color,
            group=group,
            icon=icon,
        )
        if self._world_path is None:
            self._markers = [item for item in self._markers if item.id != marker.id]
            self._markers.append(marker)
        else:
            self._marker_service.upsert(self._world_path, marker)
        self._notify()
        return marker

    def delete_marker(self, marker_id: str) -> bool:
        marker_ids = {marker.id for marker in self.markers(include_disabled=True)}
        if marker_id not in marker_ids:
            return False
        if self._world_path is None:
            before = len(self._markers)
            self._markers = [item for item in self._markers if item.id != marker_id]
            deleted = len(self._markers) != before
        else:
            deleted = self._marker_service.delete(self._world_path, marker_id)
        if deleted:
            self._notify()
        return deleted

    def search(self, query: str) -> list[MapSearchResult]:
        """解析并聚焦搜索结果；错误由 ``parse_map_query`` 原样抛出。"""
        results = parse_map_query(
            query,
            self.markers(),
            dimension_id=self._state.dimension_id,
        )
        if results:
            first = results[0]
            self._state.center_x = float(first.x)
            self._state.center_z = float(first.z)
            self._state.generation += 1
            self._notify()
        return results

    def _load_markers(self) -> None:
        if self._world_path is None:
            self._markers = []
            return
        self._markers = self._marker_service.list(
            self._world_path,
            self._state.dimension_id,
            include_disabled=True,
        )

    def _notify(self) -> None:
        if self._on_state_changed is not None:
            self._on_state_changed(self._state)

    @staticmethod
    def _coerce_dimension(item: DimensionLike) -> MapDimension:
        if isinstance(item, MapDimension):
            return item
        if not isinstance(item, Mapping):
            raise TypeError("维度必须是 MapDimension 或映射对象")
        dimension_id = str(item.get("id", ""))
        raw_scale = item.get("coordinate_scale")
        if raw_scale is None:
            raw_scale = (
                8.0
                if dimension_id in {"minecraft:the_nether", "the_nether", "DIM-1"}
                else 1.0
            )
        return MapDimension(
            id=dimension_id,
            name=str(item.get("name", item.get("id", ""))),
            region_dir=Path(str(item.get("region_dir", ""))),
            coordinate_scale=float(raw_scale or 1.0),
        )


__all__ = ["MapController"]
