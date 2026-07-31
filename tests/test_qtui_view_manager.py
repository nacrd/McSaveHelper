"""Qt 视图管理器生命周期测试。"""
from __future__ import annotations

from typing import Callable

import pytest
from PySide6.QtWidgets import QStackedWidget, QWidget

from app.qtui.context import QtFeatureContext
from app.qtui.registry import QtFeatureDescriptor, QtFeatureRegistry
from app.qtui.view_manager import QtViewManager


class _TestPage(QWidget):
    """带 dispose 计数的测试视图。"""

    def __init__(self, label: str = "") -> None:
        super().__init__()
        self.label = label
        self.dispose_calls = 0

    def dispose(self) -> None:
        self.dispose_calls += 1


def _make_manager(
    factories: dict[str, Callable[[QtFeatureContext], QWidget]],
) -> tuple[QtViewManager, QtFeatureRegistry, QStackedWidget]:
    registry = QtFeatureRegistry(
        tuple(
            QtFeatureDescriptor(
                view_id=view_id,
                translation_key=view_id,
                default_label=view_id,
                icon_glyph="•",
                factory=factory,
            )
            for view_id, factory in factories.items()
        )
    )
    stack = QStackedWidget()
    manager = QtViewManager(
        registry=registry,
        stack=stack,
        context=QtFeatureContext({}),  # type: ignore[arg-type]
    )
    return manager, registry, stack


def test_registry_requires_unique_ids(qt_app: object) -> None:
    del qt_app
    factory = lambda _ctx: QWidget()  # noqa: E731

    with pytest.raises(ValueError):
        QtFeatureRegistry(
            (
                QtFeatureDescriptor("a", "a", "a", "•", factory),
                QtFeatureDescriptor("a", "a", "a", "•", factory),
            )
        )


def test_switch_view_creates_lazily_and_tracks_current(qt_app: object) -> None:
    del qt_app
    created: list[str] = []

    def factory(ctx: QtFeatureContext) -> QWidget:
        del ctx
        page = _TestPage("alpha")
        created.append("alpha")
        return page

    manager, _registry, stack = _make_manager({"alpha": factory})

    assert manager.current_view_id is None
    assert manager.get_view("alpha") is None

    manager.switch_view("alpha")

    assert created == ["alpha"]
    assert manager.current_view_id == "alpha"
    assert stack.count() == 1
    assert manager.get_view("alpha") is not None

    # 再次切换不重复创建
    manager.switch_view("alpha")
    assert created == ["alpha"]


def test_remove_view_disposes_and_drops_state(qt_app: object) -> None:
    del qt_app
    manager, _registry, stack = _make_manager(
        {"alpha": lambda _ctx: _TestPage("alpha")}
    )
    manager.switch_view("alpha")
    view = manager.get_view("alpha")
    assert view is not None

    manager.remove_view("alpha")

    assert view.dispose_calls == 1  # type: ignore[attr-defined]
    assert manager.get_view("alpha") is None
    assert manager.current_view_id is None
    assert stack.count() == 0

    # 幂等：再次移除不重复释放
    manager.remove_view("alpha")
    assert view.dispose_calls == 1  # type: ignore[attr-defined]


def test_dispose_all_releases_every_view(qt_app: object) -> None:
    del qt_app
    pages: list[_TestPage] = []

    def factory(ctx: QtFeatureContext) -> QWidget:
        del ctx
        page = _TestPage()
        pages.append(page)
        return page

    manager, _registry, _stack = _make_manager({"alpha": factory, "beta": factory})
    manager.switch_view("alpha")
    manager.switch_view("beta")

    manager.dispose_all()

    assert all(page.dispose_calls == 1 for page in pages)
    assert manager.current_view_id is None


def test_get_top_actions_uses_view_protocol(qt_app: object) -> None:
    del qt_app

    class ActionPage(QWidget):
        def get_top_actions(self) -> list:
            return ["command-a"]

    manager, _registry, _stack = _make_manager(
        {"action": lambda _ctx: ActionPage()}
    )

    assert manager.get_top_actions("action") == ["command-a"]
    # 未提供 get_top_actions 的视图返回空列表
    manager2, _r2, _s2 = _make_manager({"plain": lambda _ctx: QWidget()})
    assert manager2.get_top_actions("plain") == []


def test_switch_view_unknown_id_raises(qt_app: object) -> None:
    del qt_app
    manager, _registry, _stack = _make_manager(
        {"alpha": lambda _ctx: QWidget()}
    )

    with pytest.raises(KeyError):
        manager.switch_view("missing")
