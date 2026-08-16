"""Qt 地图面板布局回归测试。"""
from __future__ import annotations

from PySide6.QtWidgets import QApplication, QVBoxLayout

from app.qtui.views.region_map import QtRegionMapPanel


def _translate(_key: str, default: str = "", **_kwargs: object) -> str:
    return default


def test_region_map_toolbar_has_filter_and_action_rows(
    qt_app: QApplication,
) -> None:
    panel = QtRegionMapPanel(
        _translate,
        lambda _dimension: None,
        lambda _query: None,
        lambda: None,
        lambda *_args: None,
        lambda *_args: None,
        lambda: None,
        lambda _marker: None,
        lambda *_args: None,
        lambda: None,
        lambda: None,
        lambda: None,
    )

    root_layout = panel.layout()
    assert root_layout is not None
    toolbar = root_layout.itemAt(0).layout()
    assert isinstance(toolbar, QVBoxLayout)
    assert toolbar.count() == 2
    assert all(toolbar.itemAt(index).layout() is not None for index in range(2))

    panel.deleteLater()
    qt_app.processEvents()
