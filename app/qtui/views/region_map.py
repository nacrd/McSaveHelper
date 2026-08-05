"""Qt Explorer 区域地图面板：工具栏、画布、标记列表与状态。"""
from __future__ import annotations

from typing import Callable, Mapping, Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.qtui.components.buttons import btn_danger, btn_ghost, btn_primary
from app.qtui.components.cards import muted_label, section_title
from app.qtui.views.region_map_canvas import QtRegionMapCanvas
from core.mca.map_models import MapMarker
from core.mca.region_selection import format_region_selection


Translate = Callable[..., str]
Command = Callable[[], None]
DimensionChanged = Callable[[str], None]
SearchSubmitted = Callable[[str], None]
RegionSelected = Callable[[Optional[tuple[int, int]], Optional[int]], None]
CameraChanged = Callable[[float, float, float], None]
MarkerSelected = Callable[[Optional[MapMarker]], None]
MarkerAddRequest = Callable[[str, int, int], None]

_STYLE_OPTIONS = (
    ("activity", "map.style_region", "区域"),
)
_MARKER_ID_ROLE = int(Qt.ItemDataRole.UserRole)


class QtRegionMapPanel(QWidget):
    """区域地图壳层：维度、搜索、热力画布与标记侧栏。"""

    def __init__(
        self,
        translate: Translate,
        on_dimension_changed: DimensionChanged,
        on_search: SearchSubmitted,
        on_refresh: Command,
        on_region_selected: RegionSelected,
        on_camera_changed: CameraChanged,
        on_open_nbt: Command,
        on_marker_selected: MarkerSelected,
        on_add_marker: MarkerAddRequest,
        on_delete_marker: Command,
        on_delete_region: Command,
        on_export: Command,
    ) -> None:
        """构建区域地图面板。"""
        super().__init__()
        self._translate = translate
        self._on_dimension_changed = on_dimension_changed
        self._on_search = on_search
        self._on_refresh = on_refresh
        self._on_open_nbt = on_open_nbt
        self._on_marker_selected = on_marker_selected
        self._on_add_marker = on_add_marker
        self._on_delete_marker = on_delete_marker
        self._on_delete_region = on_delete_region
        self._on_export = on_export
        self._external_region_selected = on_region_selected
        self._selected_marker_id: Optional[str] = None
        self._markers: tuple[MapMarker, ...] = ()
        self._marker_busy = False
        self._region_delete_busy = False
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
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        self._canvas = QtRegionMapCanvas(
            self._handle_region_selected,
            on_camera_changed,
            self._handle_canvas_marker,
        )
        splitter.addWidget(self._canvas)
        splitter.addWidget(self._build_marker_side())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes((760, 240))
        layout.addWidget(splitter, 1)
        self._stats = muted_label("")
        layout.addWidget(self._stats)
        self._status = QLabel("")
        self._status.setProperty("role", "muted")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._help = muted_label(self._t(
            "map.region_help",
            "拖拽平移，滚轮缩放；点击区域或标记查看详情。",
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
            "坐标 x,z / x y z / r.x.z / c.x.z / 标记名",
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
        self._open_nbt = btn_ghost(
            self._t("map.open_nbt", "打开 NBT"),
            on_click=self._on_open_nbt,
        )
        self._open_nbt.setEnabled(False)
        row.addWidget(self._open_nbt)
        self._delete_region = btn_danger(
            self._t("map.delete_region", "删除区域"),
            on_click=self._on_delete_region,
        )
        self._delete_region.setEnabled(False)
        row.addWidget(self._delete_region)
        self._export = btn_ghost(
            self._t("map.export", "导出地图"),
            on_click=self._on_export,
        )
        self._export.setEnabled(False)
        row.addWidget(self._export)
        return row

    def _build_marker_side(self) -> QWidget:
        host = QWidget()
        host.setMinimumWidth(200)
        host.setMaximumWidth(320)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(6)
        self._marker_count = muted_label(self._t(
            "map.marker_count", "{count} 个标记", count=0
        ))
        layout.addWidget(self._marker_count)
        self._marker_list = QListWidget()
        self._marker_list.currentItemChanged.connect(self._marker_item_changed)
        layout.addWidget(self._marker_list, 1)
        actions = QHBoxLayout()
        self._add_marker = btn_primary(
            self._t("map.add_marker", "添加"),
            on_click=self._prompt_add_marker,
        )
        actions.addWidget(self._add_marker)
        self._delete_marker = btn_ghost(
            self._t("map.delete_marker", "删除"),
            on_click=self._on_delete_marker,
        )
        self._delete_marker.setEnabled(False)
        actions.addWidget(self._delete_marker)
        layout.addLayout(actions)
        return host

    @property
    def canvas(self) -> QtRegionMapCanvas:
        """返回内部画布。"""
        return self._canvas

    @property
    def selected_region(self) -> Optional[tuple[int, int]]:
        """返回当前选中区域。"""
        return self._canvas.selected_region

    @property
    def selected_marker_id(self) -> Optional[str]:
        """返回当前选中标记 id。"""
        return self._selected_marker_id

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
        self.show_markers(())
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
        """填充维度下拉并选中当前维度。"""
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

    def show_markers(self, markers: Sequence[MapMarker]) -> None:
        """投影标记列表与画布针点。"""
        self._markers = tuple(markers)
        self._canvas.set_markers(markers)
        self._marker_list.blockSignals(True)
        self._marker_list.clear()
        selected_row = -1
        for index, marker in enumerate(markers):
            item = QListWidgetItem(
                f"{marker.name}\nX {marker.x} · Z {marker.z}"
            )
            item.setData(_MARKER_ID_ROLE, marker.id)
            item.setToolTip(
                f"{marker.name}\nX {marker.x}, Y {marker.y}, Z {marker.z}"
            )
            self._marker_list.addItem(item)
            if marker.id == self._selected_marker_id:
                selected_row = index
        self._marker_list.blockSignals(False)
        self._marker_count.setText(self._t(
            "map.marker_count", "{count} 个标记", count=len(markers)
        ))
        if selected_row >= 0:
            self._marker_list.setCurrentRow(selected_row)
        elif self._selected_marker_id is not None:
            self._selected_marker_id = None
            self._canvas.select_marker(None)
        self._update_marker_actions()

    def show_marker_details(self, marker: MapMarker) -> None:
        """在状态栏显示选中标记详情。"""
        self._selected_marker_id = marker.id
        self._canvas.select_marker(marker.id)
        self._status.setText(self._t(
            "map.marker_details",
            "标记 {name}\nX {x}, Y {y}, Z {z}",
            name=marker.name,
            x=marker.x,
            y=marker.y,
            z=marker.z,
        ))
        self._update_marker_actions()
        for row in range(self._marker_list.count()):
            item = self._marker_list.item(row)
            if item is not None and item.data(_MARKER_ID_ROLE) == marker.id:
                self._marker_list.blockSignals(True)
                self._marker_list.setCurrentRow(row)
                self._marker_list.blockSignals(False)
                break

    def set_marker_busy(self, busy: bool) -> None:
        """锁定标记增删按钮。"""
        self._marker_busy = busy
        self._update_marker_actions()

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

    def confirm_delete_region(self, coord: tuple[int, int]) -> bool:
        """确认删除选中区域文件。"""
        answer = QMessageBox.warning(
            self,
            self._t("map.delete_region_title", "删除区域"),
            self._t(
                "map.delete_region_message",
                "确定删除区域 r.{x}.{z}.mca？\n"
                "删除前会自动备份；游戏下次进入该区域会重新生成。",
                x=coord[0],
                z=coord[1],
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Yes

    def set_region_delete_busy(self, busy: bool) -> None:
        """锁定区域删除相关按钮。"""
        self._region_delete_busy = busy
        self._update_region_actions()

    def _handle_region_selected(
        self,
        coord: Optional[tuple[int, int]],
        size: Optional[int],
    ) -> None:
        self._selected_marker_id = None
        self._canvas.select_marker(None)
        self._marker_list.clearSelection()
        self.show_selection(coord, size)
        self._update_region_actions()
        self._update_marker_actions()
        self._external_region_selected(coord, size)

    def _handle_canvas_marker(self, marker: Optional[MapMarker]) -> None:
        if marker is None:
            return
        self.show_marker_details(marker)
        self._on_marker_selected(marker)

    def _marker_item_changed(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        if current is None:
            return
        marker_id = current.data(_MARKER_ID_ROLE)
        if not isinstance(marker_id, str):
            return
        marker = next(
            (item for item in self._markers if item.id == marker_id),
            None,
        )
        if marker is None:
            return
        self.show_marker_details(marker)
        self._on_marker_selected(marker)

    def _prompt_add_marker(self) -> None:
        center_x, center_z = self._canvas.center_block
        dialog = QDialog(self)
        dialog.setWindowTitle(self._t("map.add_marker_title", "添加地图标记"))
        form = QFormLayout(dialog)
        name_field = QLineEdit(self._t("map.default_marker_name", "新标记"))
        x_field = QLineEdit(str(int(center_x)))
        z_field = QLineEdit(str(int(center_z)))
        form.addRow(self._t("map.marker_name", "名称"), name_field)
        form.addRow("X", x_field)
        form.addRow("Z", z_field)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name = name_field.text().strip()
        if not name:
            return
        try:
            x = int(float(x_field.text().strip()))
            z = int(float(z_field.text().strip()))
        except ValueError:
            return
        self._on_add_marker(name, x, z)

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

    def _update_marker_actions(self) -> None:
        enabled = self._dimension.isEnabled() and not self._marker_busy
        self._add_marker.setEnabled(enabled)
        self._delete_marker.setEnabled(
            enabled and self._selected_marker_id is not None
        )

    def _update_region_actions(self) -> None:
        has_region = self._canvas.selected_region is not None
        base = self._dimension.isEnabled() and not self._region_delete_busy
        self._open_nbt.setEnabled(base and has_region)
        self._delete_region.setEnabled(base and has_region)
        self._export.setEnabled(self._dimension.isEnabled())

    def _set_controls_enabled(self, enabled: bool) -> None:
        self._dimension.setEnabled(enabled)
        self._search.setEnabled(enabled)
        self._canvas.setEnabled(enabled)
        self._marker_list.setEnabled(enabled)
        if not enabled:
            self._selected_marker_id = None
        self._update_region_actions()
        self._update_marker_actions()


__all__ = ["QtRegionMapPanel"]
