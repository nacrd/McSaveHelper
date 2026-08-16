"""Qt 区域地图面板与后台扫描、MapController、标记任务的协调器。"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional, Protocol, cast

from app.controllers.map_controller import MapController
from app.controllers.topview_tile_requests import (
    TopviewTileRequestCoordinator,
)
from app.controllers.region_delete_controller import (
    RegionDeleteBusyError,
    RegionDeleteController,
    RegionDeleteOutcome,
    RegionDeleteRequest,
    RegionDeleteStatus,
)
from app.qtui.context import (
    QtDialogPort,
    QtFileDialogPort,
    QtProgressPort,
    QtRuntimePort,
    QtTranslationPort,
)
from app.qtui.utils import run_on_ui
from app.qtui.views.map_export_dialog import (
    MapExportSession,
    QtMapExportDialog,
)
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
from app.services.region_map import RegionMapService
from app.services.world_transaction import WorldTransactionService
from core.mca.map_models import BLOCKS_PER_REGION, MapMarker
from core.mca.map_search import MapSearchError
from core.omni.world_session import WorldSession
from core.region_utils import DimensionInfo


class QtRegionMapHost(
    QtTranslationPort,
    QtDialogPort,
    QtFileDialogPort,
    QtProgressPort,
    QtRuntimePort,
    Protocol,
):
    """区域地图所需的应用端口。"""

    @property
    def world_transactions(self) -> WorldTransactionService:
        """世界事务服务（框架中立端口）。"""
        ...


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
        self._region_delete_scope = app.execution_runtime.create_scope(
            "qt_region_map_delete"
        )
        self._region_delete_controller = RegionDeleteController(
            self._region_delete_scope,
            app.world_transactions,
        )
        create_map = cast(
            Callable[[], RegionMapService] | None,
            getattr(app, "create_region_map_service", None),
        )
        if create_map is not None:
            self._map_service: RegionMapService = create_map()
        else:
            self._map_service = RegionMapService(app.execution_runtime)
        self._map_service.set_tile_ready_callback(self._on_topview_tile_ready)
        self._tile_requests = TopviewTileRequestCoordinator(self._map_service)
        self._style_id = "topview"
        self._map_export_dialog = QtMapExportDialog(app)
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
            on_delete_region=self._delete_selected_region,
            on_export=self._open_map_export_dialog,
            on_style_changed=self._on_style_changed,
        )
        self.panel.set_style("topview")
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
        self._map_export_dialog.invalidate_session()
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
        """取消扫描/删除并恢复空状态。"""
        self._host_generation += 1
        self._map_export_dialog.invalidate_session()
        self._region_delete_controller.cancel()
        self.panel.set_region_delete_busy(False)
        self._tasks.clear()
        self._tile_requests.reset()
        self._map_service.clear_data()
        self.panel.canvas.clear_tiles()
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
        if coord is not None and self._style_id == "topview":
            self._tile_requests.request_region_detail(
                coord,
                available_regions=tuple(self.panel.canvas._regions.keys()),
            )
            self._request_visible_tiles()

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

    def _delete_selected_region(self) -> None:
        """校验内存选择，并把区域删除提交到共享 I/O 通道。"""
        session = self._session
        coord = self._selected_region
        if session is None or coord is None:
            self._app.warn_dialog(
                self._t("map.notice", "提示"),
                self._t("map.select_region_first", "请先在地图中选择一个区域。"),
            )
            return
        if not self.panel.confirm_delete_region(coord):
            return
        region_dir = self._dimension_dirs.get(self._current_dimension)
        if region_dir is None:
            self._app.warn_dialog(
                self._t("map.notice", "提示"),
                self._t("map.missing_region_dir", "未找到当前维度的 region 目录"),
            )
            return
        region_path = region_dir / f"r.{coord[0]}.{coord[1]}.mca"
        world_path = session.world_path
        request = RegionDeleteRequest(
            world_path=world_path,
            region_path=region_path,
            coord=coord,
            generation=self._host_generation,
        )
        self.panel.set_region_delete_busy(True)
        try:
            self._region_delete_controller.start(
                request,
                lambda outcome: run_on_ui(
                    self._apply_region_delete_outcome,
                    outcome,
                ),
            )
        except RegionDeleteBusyError:
            self.panel.set_region_delete_busy(False)
            self._app.warn_dialog(
                self._t("region_delete.busy_title", "删除进行中"),
                self._t(
                    "region_delete.busy_message",
                    "已有区域删除正在执行，请等待当前操作完成。",
                ),
            )
        except (TaskQueueFullError, RuntimeClosedError):
            self.panel.set_region_delete_busy(False)
            self._app.warn_dialog(
                self._t("region_delete.queue_full_title", "后台任务繁忙"),
                self._t(
                    "region_delete.queue_full_message",
                    "后台 I/O 队列已满，请稍后重试。",
                ),
            )
        except Exception as error:
            self.panel.set_region_delete_busy(False)
            self._app.handle_exception(
                error,
                title=self._t("map.delete_region_failed", "删除区域失败"),
            )

    def _apply_region_delete_outcome(
        self,
        outcome: RegionDeleteOutcome,
    ) -> None:
        """在 UI 线程投影区域删除终态，并拒绝过期结果。"""
        self.panel.set_region_delete_busy(False)
        request = outcome.request
        session = self._session
        if (
            request.generation != self._host_generation
            or session is None
            or session.world_path.resolve() != request.world_path.resolve()
        ):
            self._app.log(
                f"丢弃过期区域删除回调: {request.region_path}",
                "INFO",
            )
            return
        if outcome.status is RegionDeleteStatus.CANCELLED:
            self._app.warn_dialog(
                self._t("region_delete.cancelled_title", "删除已取消"),
                self._t(
                    "region_delete.cancelled_message",
                    "区域删除已在安全检查点取消，原存档保持不变。",
                ),
            )
            return
        if outcome.status is RegionDeleteStatus.FAILED:
            error = outcome.error or RuntimeError("区域删除失败")
            self._app.handle_exception(
                error,
                title=self._t("map.delete_region_failed", "删除区域失败"),
            )
            return
        result = outcome.result
        if result is None or not result.value:
            self._app.warn_dialog(
                self._t("map.notice", "提示"),
                self._t("map.delete_region_failed", "删除区域失败"),
            )
            return
        backup_name = result.backup.backup_path.name
        self._app.info_dialog(
            self._t("map.notice", "提示"),
            self._t(
                "map.delete_region_success",
                "已删除区域 r.{x}.{z}.mca，游戏下次进入会重新生成。"
                "安全备份: {backup}",
                x=request.coord[0],
                z=request.coord[1],
                backup=backup_name,
            ),
        )
        self._selected_region = None
        self.refresh()

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

    def _open_map_export_dialog(self) -> None:
        """打开导出对话框，预填当前世界/维度/选区。"""
        session = self._session
        if session is None:
            self._app.warn_dialog(
                self._t("map.notice", "提示"),
                self._t("map.select_save_first", "请先设置当前存档。"),
            )
            return
        self._map_export_dialog.open(MapExportSession(
            world_path=session.world_path,
            dimension_id=self._current_dimension or "overworld",
            selected_region=self._selected_region,
        ))

    def _on_camera_changed(
        self,
        center_x: float,
        center_z: float,
        scale: float,
    ) -> None:
        self._map_controller.update_camera(center_x, center_z, scale)
        self._request_visible_tiles()

    def _scan_ready(self, result: RegionScanResult, generation: int) -> None:
        del generation
        self.panel.show_regions(result.sizes, total_bytes=result.total_bytes)
        self._seed_topview_inventory(result)
        self._request_visible_tiles()

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

    def _on_style_changed(self, style_id: str) -> None:
        self._style_id = style_id
        self.panel.canvas.set_display_mode(
            "topview" if style_id == "topview" else "activity"
        )
        if style_id == "topview":
            self._request_visible_tiles()
        else:
            self.panel.canvas.update()

    def _seed_topview_inventory(self, result: RegionScanResult) -> None:
        regions: dict[tuple[int, int], Path] = {}
        for coord in result.sizes:
            path = result.region_dir / f"r.{coord[0]}.{coord[1]}.mca"
            if path.is_file():
                regions[coord] = path
        self._tile_requests.reset()
        self.panel.canvas.clear_tiles()
        self._map_service.seed_region_inventory(
            regions,
            sizes=dict(result.sizes),
        )

    def _request_visible_tiles(self) -> None:
        if self._style_id != "topview" or self._session is None:
            return
        visible = self.panel.canvas.visible_regions()
        if not visible:
            return
        tile_scale = self.panel.canvas.tile_scale
        needed = self._tile_requests.visible_base_tile_size(tile_scale)
        center = (
            int(self.panel.canvas.center_block[0] // BLOCKS_PER_REGION),
            int(self.panel.canvas.center_block[1] // BLOCKS_PER_REGION),
        )
        missing: list[tuple[int, int]] = []
        for coord in visible:
            raw = self._map_service.get_topview_tile(coord)
            if raw:
                self.panel.canvas.set_tile(coord, raw)
            if not self._map_service.has_topview_tile(coord, min_size=needed):
                missing.append(coord)
        if missing:
            self._tile_requests.request_visible(
                missing,
                visible_regions=visible,
                scale=tile_scale,
                center=center,
            )
        self._tile_requests.request_selected_detail(
            scale=tile_scale,
            selected=self._selected_region,
            center=center,
            available_regions=tuple(self.panel.canvas._regions.keys()),
            enabled=True,
        )

    def _on_topview_tile_ready(self, coord: tuple[int, int]) -> None:
        def apply() -> None:
            raw = self._map_service.get_topview_tile(coord)
            if raw:
                self.panel.canvas.set_tile(coord, raw)
            should_retry = self._tile_requests.on_tile_ready(coord)
            if should_retry:
                self._request_visible_tiles()

        run_on_ui(apply)

    def _t(self, key: str, default: str = "", **kwargs: object) -> str:
        return self._app.translate(key, default, **kwargs)

    def close(self) -> None:
        """幂等关闭扫描任务、导出/删除/标记作用域与地图控制器。"""
        self._host_generation += 1
        self._map_export_dialog.dispose()
        self._region_delete_controller.cancel()
        self.panel.set_region_delete_busy(False)
        self._tasks.close()
        self._tile_requests.reset()
        self._map_service.set_tile_ready_callback(None)
        self._map_service.close()
        self._map_controller.close()
        self._marker_scope.close()
        self._region_delete_scope.close()
        self._session = None
        self._dimension_dirs.clear()


__all__ = ["QtRegionMapCoordinator", "QtRegionMapHost"]
