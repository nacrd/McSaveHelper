"""Qt 区域地图面板与后台扫描、MapController 的协调器。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Protocol

from app.controllers.map_controller import MapController
from app.qtui.context import (
    QtDialogPort,
    QtRuntimePort,
    QtTranslationPort,
)
from app.qtui.views.region_map import QtRegionMapPanel
from app.qtui.views.region_map_tasks import (
    RegionMapTaskCallbacks,
    RegionMapTasks,
    RegionScanResult,
)
from app.services.map_marker_service import MapMarkerService
from core.mca.map_models import BLOCKS_PER_REGION
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
    """连接区域地图面板、维度会话与扫描任务。"""

    def __init__(self, app: QtRegionMapHost) -> None:
        """创建协调器与面板。

        Args:
            app: 翻译、对话框与执行运行时端口。
        """
        self._app = app
        self._session: WorldSession | None = None
        self._dimension_dirs: dict[str, Path] = {}
        self._current_dimension = ""
        self._selected_region: tuple[int, int] | None = None
        self._map_controller = MapController(MapMarkerService())
        self.panel = QtRegionMapPanel(
            app.translate,
            self._on_dimension_changed,
            self._on_search,
            self.refresh,
            self._on_region_selected,
            self._on_camera_changed,
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

    def set_world(self, session: WorldSession) -> None:
        """绑定世界、刷新维度列表并扫描当前维度。"""
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

    def clear_world(self) -> None:
        """取消扫描并恢复空状态。"""
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
        if hit.kind in {"region", "chunk", "block"}:
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
        """幂等关闭扫描任务与地图控制器。"""
        self._tasks.close()
        self._map_controller.close()
        self._session = None
        self._dimension_dirs.clear()


__all__ = ["QtRegionMapCoordinator", "QtRegionMapHost"]
