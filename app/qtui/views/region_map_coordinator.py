"""Qt 区域地图面板与后台扫描、MapController、标记任务的协调器。"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional, Protocol

from app.controllers.map_controller import MapController
from app.qtui.context import (
    QtDialogPort,
    QtRuntimePort,
    QtTranslationPort,
)
from app.qtui.utils import run_on_ui
from app.qtui.views.region_map import QtRegionMapPanel
from app.qtui.views.region_map_tasks import (
    RegionMapTaskCallbacks,
    RegionMapTasks,
    RegionScanResult,
)
from app.services.execution_runtime import (
    RuntimeClosedError,
    TaskQueueFullError,
)
from app.services.map_marker_service import MapMarkerService
from core.mca.map_models import BLOCKS_PER_REGION, MapMarker
from core.mca.map_search import MapSearchError
from core.omni.world_session import WorldSession
from core.region_utils import DimensionInfo


class QtRegionMapHost(
    QtTranslationPort,
    QtDialogPort,
    QtRuntimePort,
    Protocol,
):
    """区域地图所需的应用端口。"""


class QtRegionMapCoordinator:
    """连接区域地图面板、维度会话、扫描任务与标记操作。"""

    def __init__(
        self,
        app: QtRegionMapHost,
        on_open_region_nbt: Callable[[int, int, str], None] | None = None,
        on_dimension_synced: Callable[[str], None] | None = None,
        *,
        marker_service: MapMarkerService | None = None,
    ) -> None:
        """创建协调器与面板。

        Args:
            app: 翻译、对话框与执行运行时端口。
            on_open_region_nbt: 打开选中区域 NBT 的回调。
            on_dimension_synced: 维度切换后同步给 NBT 等模块。
            marker_service: 可选标记持久化服务（测试可注入临时根目录）。
        """
        self._app = app
        self._on_open_region_nbt = on_open_region_nbt
        self._on_dimension_synced = on_dimension_synced
        self._session: WorldSession | None = None
        self._dimension_dirs: dict[str, Path] = {}
        self._current_dimension = ""
        self._selected_region: tuple[int, int] | None = None
        self._host_generation = 0
        self._marker_scope = app.execution_runtime.create_scope(
            "qt_region_map_markers"
        )
        self._map_controller = MapController(
            marker_service or MapMarkerService(),
            task_scope=self._marker_scope,
            post_to_ui=lambda callback: run_on_ui(callback),
            get_generation=lambda: self._host_generation,
        )
        self.panel = QtRegionMapPanel(
            app.translate,
            self._on_dimension_changed,
            self._on_search,
            self.refresh,
            self._on_region_selected,
            self._on_camera_changed,
            self._open_selected_nbt,
            self._on_marker_selected,
            self._add_marker,
            self._delete_selected_marker,
        )
        self._tasks = RegionMapTasks(
            app.execution_runtime,
            RegionMapTaskCallbacks(
                scan_ready=self._scan_ready,
                scan_error=self._scan_error,
                scan_progress=self._scan_progress,
            ),
        )

    @property
    def selected_region(self) -> tuple[int, int] | None:
        """返回当前选中区域坐标。"""
        return self._selected_region

    @property
    def current_dimension(self) -> str:
        """返回当前维度 id。"""
        return self._current_dimension

    @property
    def map_controller(self) -> MapController:
        """返回地图会话控制器（测试用）。"""
        return self._map_controller

    def set_world(self, session: WorldSession) -> None:
        """绑定世界、刷新维度列表并扫描当前维度。"""
        self._host_generation += 1
        self._session = session
        self._selected_region = None
        dimensions = self._read_dimensions(session)
        self._dimension_dirs = {
            item["id"]: Path(item["region_dir"]) for item in dimensions
        }
        self._map_controller.bind_world(session.world_path, dimensions)
        ordered = [
            (item["id"], item["name"]) for item in dimensions
        ]
        current = self._map_controller.snapshot.dimension_id
        if current not in self._dimension_dirs and ordered:
            current = ordered[0][0]
        self._current_dimension = current
        self.panel.set_dimensions(ordered, current)
        if not ordered:
            self.panel.show_empty()
            self.panel.show_stats_message(self._t(
                "map.no_dimensions", "当前存档没有可浏览的维度"
            ))
            return
        self.refresh()
        self._request_marker_load()

    def clear_world(self) -> None:
        """取消扫描并恢复空状态。"""
        self._host_generation += 1
        self._tasks.clear()
        self._map_controller.unbind_world()
        self._session = None
        self._dimension_dirs.clear()
        self._current_dimension = ""
        self._selected_region = None
        self.panel.show_empty()

    def refresh(self) -> None:
        """重新扫描当前维度的 region 目录。"""
        if self._session is None or not self._current_dimension:
            return
        region_dir = self._dimension_dirs.get(self._current_dimension)
        if region_dir is None:
            self.panel.show_scan_error(self._t(
                "map.missing_region_dir", "未找到当前维度的 region 目录"
            ))
            return
        if not region_dir.exists():
            self.panel.show_scan_error(self._t(
                "map.region_dir_missing", "region 目录不存在"
            ))
            return
        self._selected_region = None
        self.panel.show_scanning()
        try:
            self._tasks.scan_regions(region_dir)
        except (RuntimeError, ValueError) as error:
            self._scan_error(error, self._tasks.world_generation)

    def _read_dimensions(self, session: WorldSession) -> list[DimensionInfo]:
        raw = session.get_dimensions()
        result: list[DimensionInfo] = []
        for item in raw:
            if isinstance(item, dict):
                dimension_id = str(item.get("id", "") or "")
                region_dir = str(item.get("region_dir", "") or "")
                if not dimension_id or not region_dir:
                    continue
                result.append(DimensionInfo(
                    id=dimension_id,
                    name=str(item.get("name") or dimension_id),
                    region_dir=region_dir,
                    coordinate_scale=float(item.get("coordinate_scale") or 1.0),
                ))
        return result

    def _on_dimension_changed(self, dimension_id: str) -> None:
        if (
            self._session is None
            or dimension_id == self._current_dimension
            or dimension_id not in self._dimension_dirs
        ):
            return
        center_x, center_z = self.panel.canvas.center_block
        self._map_controller.update_camera(
            center_x, center_z, self.panel.canvas.scale
        )
        try:
            self._map_controller.switch_dimension(dimension_id)
        except KeyError as error:
            self._app.handle_exception(
                error,
                title=self._t("map.dimension_switch_failed", "切换维度失败"),
            )
            return
        self._current_dimension = dimension_id
        self._selected_region = None
        state = self._map_controller.snapshot
        self.refresh()
        self.panel.set_camera(state.center_x, state.center_z, state.scale)
        self._request_marker_load()
        if self._on_dimension_synced is not None:
            self._on_dimension_synced(dimension_id)

    def _on_search(self, query: str) -> None:
        text = query.strip()
        if not text:
            return
        try:
            results = self._map_controller.search(text)
        except MapSearchError as error:
            self._app.warn_dialog(
                self._t("map.notice", "提示"),
                str(error),
            )
            return
        if not results:
            self._app.warn_dialog(
                self._t("map.notice", "提示"),
                self._t("map.search_empty", "没有匹配的搜索结果"),
            )
            return
        hit = results[0]
        self.panel.focus_block(float(hit.x), float(hit.z))
        if hit.kind == "marker" and hit.marker_id:
            marker = next(
                (
                    item for item in self._map_controller.markers()
                    if item.id == hit.marker_id
                ),
                None,
            )
            if marker is not None:
                self.panel.show_marker_details(marker)
        elif hit.kind in {"region", "chunk", "block"}:
            region = (
                int(hit.x // BLOCKS_PER_REGION),
                int(hit.z // BLOCKS_PER_REGION),
            )
            self.panel.canvas.select_region(region)
        self._app.log(
            f"地图搜索命中: {hit.kind} ({hit.x}, {hit.z})",
            "INFO",
        )

    def _on_region_selected(
        self,
        coord: Optional[tuple[int, int]],
        size: Optional[int],
    ) -> None:
        del size
        self._selected_region = coord

    def _on_marker_selected(self, marker: Optional[MapMarker]) -> None:
        if marker is None:
            return
        full = next(
            (
                item for item in self._map_controller.markers()
                if item.id == marker.id
            ),
            marker,
        )
        self.panel.show_marker_details(full)
        self.panel.focus_block(float(full.x), float(full.z), scale=max(
            self.panel.canvas.scale, 0.12
        ))

    def _add_marker(self, name: str, x: int, z: int) -> None:
        if self._session is None:
            self._app.warn_dialog(
                self._t("map.notice", "提示"),
                self._t("map.select_save_first", "请先设置当前存档。"),
            )
            return
        self.panel.set_marker_busy(True)
        try:
            self._map_controller.submit_upsert_marker(
                name,
                x,
                z,
                on_complete=self._finish_marker_upsert,
                on_error=self._handle_marker_error,
            )
        except (
            KeyError,
            RuntimeClosedError,
            RuntimeError,
            TaskQueueFullError,
            ValueError,
        ) as error:
            self._handle_marker_error(error)

    def _delete_selected_marker(self) -> None:
        marker_id = self.panel.selected_marker_id
        if not marker_id:
            self._app.warn_dialog(
                self._t("map.notice", "提示"),
                self._t("map.select_marker_first", "请先选择一个标记。"),
            )
            return
        self.panel.set_marker_busy(True)
        try:
            self._map_controller.submit_delete_marker(
                marker_id,
                on_complete=self._finish_marker_delete,
                on_error=self._handle_marker_error,
            )
        except (
            KeyError,
            RuntimeClosedError,
            RuntimeError,
            TaskQueueFullError,
            ValueError,
        ) as error:
            self._handle_marker_error(error)

    def _request_marker_load(self) -> None:
        if self._session is None or self._map_controller.world_path is None:
            self.panel.show_markers(())
            return
        self.panel.set_marker_busy(True)
        try:
            self._map_controller.submit_load_markers(
                self._finish_marker_load,
                self._handle_marker_error,
            )
        except (
            RuntimeClosedError,
            RuntimeError,
            TaskQueueFullError,
            ValueError,
        ) as error:
            self._handle_marker_error(error)

    def _finish_marker_load(self) -> None:
        self.panel.set_marker_busy(False)
        self.panel.show_markers(self._map_controller.markers())

    def _finish_marker_upsert(self, marker: MapMarker) -> None:
        self.panel.set_marker_busy(False)
        self.panel.show_markers(self._map_controller.markers())
        self.panel.show_marker_details(marker)
        self.panel.focus_block(float(marker.x), float(marker.z))
        self._app.log(f"已添加地图标记: {marker.name}", "INFO")

    def _finish_marker_delete(self, deleted: bool) -> None:
        self.panel.set_marker_busy(False)
        self.panel.show_markers(self._map_controller.markers())
        if deleted:
            self._app.log("已删除地图标记", "INFO")

    def _handle_marker_error(self, error: Exception) -> None:
        self.panel.set_marker_busy(False)
        self._app.handle_exception(
            error,
            title=self._t("map.marker_operation_failed", "地图标记操作失败"),
        )

    def _open_selected_nbt(self) -> None:
        if self._selected_region is None:
            self._app.warn_dialog(
                self._t("map.notice", "提示"),
                self._t("map.select_region_first", "请先在地图中选择一个区域。"),
            )
            return
        if self._on_open_region_nbt is None:
            return
        region_x, region_z = self._selected_region
        self._on_open_region_nbt(
            region_x,
            region_z,
            self._current_dimension or "overworld",
        )

    def _on_camera_changed(
        self,
        center_x: float,
        center_z: float,
        scale: float,
    ) -> None:
        self._map_controller.update_camera(center_x, center_z, scale)

    def _scan_ready(self, result: RegionScanResult, generation: int) -> None:
        del generation
        self.panel.show_regions(result.sizes, total_bytes=result.total_bytes)

    def _scan_error(self, error: Exception, generation: int) -> None:
        del generation
        self.panel.show_scan_error(str(error))
        self._app.handle_exception(
            error,
            title=self._t("map.scan_failed_title", "扫描区域地图失败"),
        )

    def _scan_progress(
        self,
        value: float,
        stage: str,
        generation: int,
    ) -> None:
        del generation, stage
        self.panel.show_stats_message(self._t(
            "map.scanning_progress",
            "正在扫描区域文件... {percent}%",
            percent=int(value * 100),
        ))

    def _t(self, key: str, default: str = "", **kwargs: object) -> str:
        return self._app.translate(key, default, **kwargs)

    def close(self) -> None:
        """幂等关闭扫描任务、标记作用域与地图控制器。"""
        self._host_generation += 1
        self._tasks.close()
        self._map_controller.close()
        self._marker_scope.close()
        self._session = None
        self._dimension_dirs.clear()


__all__ = ["QtRegionMapCoordinator", "QtRegionMapHost"]
