"""Qt 全局动效系统测试。"""
from __future__ import annotations

from PySide6.QtWidgets import QApplication, QWidget

from app.qtui.animation import QtAnimationSystem, QtMotionTokens


def test_reduced_motion_completes_without_animation(qt_app: QApplication) -> None:
    widget = QWidget()
    widget.show()
    qt_app.processEvents()
    completed: list[bool] = []
    animations = QtAnimationSystem(reduced_motion=True)

    animations.fade_in(widget, on_finished=lambda: completed.append(True))

    assert animations.active_count == 0
    assert widget.graphicsEffect() is None
    assert completed == [True]
    widget.deleteLater()


def test_enabling_reduced_motion_stops_active_fade(qt_app: QApplication) -> None:
    widget = QWidget()
    widget.show()
    qt_app.processEvents()
    animations = QtAnimationSystem(tokens=QtMotionTokens(500, 500, 500))

    animations.fade_in(widget)
    assert animations.active_count == 1

    animations.set_reduced_motion(True)

    assert animations.active_count == 0
    assert widget.graphicsEffect() is None
    widget.deleteLater()


def test_width_animation_reaches_target(qt_app: QApplication) -> None:
    widget = QWidget()
    widget.setFixedWidth(80)
    widget.show()
    qt_app.processEvents()
    animations = QtAnimationSystem(tokens=QtMotionTokens(20, 20, 20))

    animations.animate_width(widget, 180)
    assert animations.active_count == 1
    qt_app.processEvents()
    qt_app.processEvents()
    animations.stop(widget)

    assert widget.width() >= 80
    widget.deleteLater()
