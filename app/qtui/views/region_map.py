"""Qt Explorer 区域地图面板：工具栏、画布与状态。"""
from __future__ import annotations

from typing import Callable, Mapping, Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from app.qtui.components.buttons import btn_ghost, btn_primary
from app.qtui.components.cards import muted_label, section_title
from app.qtui.views.region_map_canvas import QtRegionMapCanvas
from core.mca.region_selection import format_region_selection


Translate = Callable[..., str]
Command = Callable[[], None]
DimensionChanged = Callable[[str], None]
SearchSubmitted = Callable[[str], None]
RegionSelected = Callable[[Optional[tuple[int, int]], Optional[int]], None]
CameraChanged = Callable[[float, float, float], None]

_STYLE_OPTIONS = (
    ("activity", "map.style_region", "区域"),
)


class QtRegionMapPanel(QWidget):
    """区域地图壳层：维度、搜索、缩放与热力画布。"""

    def __init__(
        self,
        translate: Translate,
        on_dimension_changed: DimensionChanged,
        on_search: SearchSubmitted,
        on_refresh: Command,
        on_region_selected: RegionSelected,
        on_camera_changed: CameraChanged,
    ) -> None:
        """构建区域地图面板。

        Args:
            translate: UI 翻译回调。
            on_dimension_changed: 维度 id 变更回调。
            on_search: 搜索提交回调。
            on_refresh: 重新扫描当前维度。
            on_region_selected: 画布区域选择回调。
            on_camera_changed: 镜头变化回调。
        """
        super().__init__()
        self._translate = translate
        self._on_dimension_changed = on_dimension_changed
        self._on_search = on_search
        self._on_refresh = on_refresh
        self._external_region_selected = on_region_selected
        self._build(on_region_selected, on_camera_changed)
        self.show_empty()

    def _t(self, key: str, default: str = "", **kwargs: object) -> str:
        return self._translate(key, default, **kwargs)

    def _build(
        self,
        on_region_selected: RegionSelected,
        on_camera_changed: CameraChanged,
    ) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(section_title(self._t("explorer.tab_map", "地图")))
        layout.addLayout(self._build_toolbar())
        self._canvas = QtRegionMapCanvas(
            self._handle_region_selected,
            on_camera_changed,
        )
        layout.addWidget(self._canvas, 1)
        self._stats = muted_label("")
        layout.addWidget(self._stats)
        self._status = QLabel("")
        self._status.setProperty("role", "muted")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._help = muted_label(self._t(
            "map.region_help",
            "拖拽平移，滚轮缩放；点击区域查看详情。首批为区域活动热力图。",
        ))
        layout.addWidget(self._help)
        del on_region_selected

    def _build_toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        self._dimension = QComboBox()
        self._dimension.setMinimumWidth(160)
        self._dimension.currentIndexChanged.connect(self._dimension_index_changed)
        row.addWidget(self._dimension)
        self._style = QComboBox()
        for value, key, default in _STYLE_OPTIONS:
            self._style.addItem(self._t(key, default), value)
        self._style.setEnabled(False)
        row.addWidget(self._style)
        self._search = QLineEdit()
        self._search.setPlaceholderText(self._t(
            "map.search_hint",
            "坐标 x,z / x y z / r.x.z / c.x.z",
        ))
        self._search.returnPressed.connect(self._submit_search)
        row.addWidget(self._search, 1)
        row.addWidget(btn_ghost(
            self._t("map.search", "搜索"),
            on_click=self._submit_search,
        ))
        row.addWidget(btn_ghost(
            self._t("map.zoom_in", "放大"),
            on_click=self._zoom_in,
        ))
        row.addWidget(btn_ghost(
            self._t("map.zoom_out", "缩小"),
            on_click=self._zoom_out,
        ))
        row.addWidget(btn_ghost(
            self._t("map.reset_view", "复位"),
            on_click=self._reset_view,
        ))
        row.addWidget(btn_primary(
            self._t("map.refresh", "刷新"),
            on_click=self._on_refresh,
        ))
        return row

    @property
    def canvas(self) -> QtRegionMapCanvas:
        """返回内部画布。"""
        return self._canvas

    @property
    def selected_region(self) -> Optional[tuple[int, int]]:
        """返回当前选中区域。"""
        return self._canvas.selected_region

    @property
    def current_dimension_id(self) -> str:
        """返回维度下拉当前 id。"""
        return str(self._dimension.currentData() or "")

    def show_empty(self) -> None:
        """未加载存档时的空状态。"""
        self._dimension.blockSignals(True)
        self._dimension.clear()
        self._dimension.blockSignals(False)
        self._canvas.clear()
        self._stats.setText(self._t("map.no_world", "加载存档后可浏览区域地图"))
        self._status.setText("")
        self._set_controls_enabled(False)

    def show_scanning(self) -> None:
        """显示扫描进行中状态。"""
        self._stats.setText(self._t("map.scanning", "正在扫描区域文件..."))
        self._status.setText("")
        self._set_controls_enabled(True)

    def set_dimensions(
        self,
        dimensions: Sequence[tuple[str, str]],
        current_id: str,
    ) -> None:
        """填充维度下拉并选中当前维度。

        Args:
            dimensions: ``(id, display_name)`` 序列。
            current_id: 当前维度 id。
        """
        self._dimension.blockSignals(True)
        self._dimension.clear()
        selected = 0
        for index, (dimension_id, name) in enumerate(dimensions):
            self._dimension.addItem(name, dimension_id)
            if dimension_id == current_id:
                selected = index
        if dimensions:
            self._dimension.setCurrentIndex(selected)
        self._dimension.blockSignals(False)
        self._set_controls_enabled(bool(dimensions))

    def show_regions(
        self,
        regions: Mapping[tuple[int, int], int],
        *,
        total_bytes: int,
    ) -> None:
        """投影扫描结果到画布与统计条。"""
        self._canvas.set_regions(regions)
        count = len(regions)
        size_mb = total_bytes / (1024 * 1024)
        self._stats.setText(self._t(
            "map.region_stats",
            "已生成区域: {count} 个 · 总大小 {size:.1f} MB",
            count=count,
            size=size_mb,
        ))
        if self._canvas.selected_region is None:
            self._status.setText(self._t(
                "map.scan_done_hint",
                "扫描完成：点击区域查看详情",
            ))

    def show_scan_error(self, message: str) -> None:
        """显示扫描失败摘要。"""
        self._stats.setText(self._t(
            "map.scan_failed", "扫描失败: {error}", error=message
        ))

    def show_stats_message(self, message: str) -> None:
        """更新统计条文本。"""
        self._stats.setText(message)

    def show_selection(
        self,
        coord: Optional[tuple[int, int]],
        size: Optional[int],
    ) -> None:
        """更新选中区域状态文本。"""
        if coord is None:
            self._status.setText(self._t(
                "map.scan_done_hint",
                "扫描完成：点击区域查看详情",
            ))
            return
        detail = {}
        if size is not None:
            detail["size_bytes"] = size
        text = format_region_selection(coord, detail)
        if size is not None:
            text = f"{text}\n大小 {size / 1024:.1f} KB"
        self._status.setText(text)

    def focus_block(
        self,
        block_x: float,
        block_z: float,
        *,
        scale: Optional[float] = None,
    ) -> None:
        """转发镜头聚焦。"""
        self._canvas.focus_block(block_x, block_z, scale=scale)

    def set_camera(self, center_x: float, center_z: float, scale: float) -> None:
        """写入画布镜头。"""
        self._canvas.set_camera(center_x, center_z, scale)

    def _handle_region_selected(
        self,
        coord: Optional[tuple[int, int]],
        size: Optional[int],
    ) -> None:
        self.show_selection(coord, size)
        self._external_region_selected(coord, size)

    def _dimension_index_changed(self, _index: int) -> None:
        dimension_id = self.current_dimension_id
        if dimension_id:
            self._on_dimension_changed(dimension_id)

    def _submit_search(self) -> None:
        self._on_search(self._search.text())

    def _zoom_in(self) -> None:
        center_x, center_z = self._canvas.center_block
        self._canvas.focus_block(
            center_x, center_z, scale=self._canvas.scale * 1.25
        )

    def _zoom_out(self) -> None:
        center_x, center_z = self._canvas.center_block
        self._canvas.focus_block(
            center_x, center_z, scale=self._canvas.scale / 1.25
        )

    def _reset_view(self) -> None:
        self._canvas.fit_to_regions()

    def _set_controls_enabled(self, enabled: bool) -> None:
        self._dimension.setEnabled(enabled)
        self._search.setEnabled(enabled)
        self._canvas.setEnabled(enabled)


__all__ = ["QtRegionMapPanel"]
