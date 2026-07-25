"""Explorer 懒加载搜索标签的当前存档上下文回归。"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from app.ui.views.explorer.explorer_view import ExplorerView


class _SearchViewProbe:
    """记录懒构建后收到的当前存档路径。"""

    instances: list["_SearchViewProbe"] = []

    def __init__(self, app: object, *, compact: bool) -> None:
        self.app = app
        self.compact = compact
        self.selected_paths: list[str] = []
        self.instances.append(self)

    def on_save_selected(self, path: str) -> None:
        self.selected_paths.append(path)


def _bare_view(current_save_path: str | None) -> ExplorerView:
    view = ExplorerView.__new__(ExplorerView)
    view.app = cast(
        Any,
        SimpleNamespace(current_save_path=current_save_path),
    )
    view._compact_mode = True
    view._tab_search = cast(Any, SimpleNamespace(content=None))
    return view


def test_lazy_search_tab_receives_already_selected_world(monkeypatch) -> None:
    _SearchViewProbe.instances.clear()
    monkeypatch.setattr(
        "app.ui.views.explorer.explorer_view.EntityBlockSearchView",
        _SearchViewProbe,
    )
    view = _bare_view("C:/saves/current-world")

    view._build_search_tab()

    probe = _SearchViewProbe.instances[0]
    assert probe.compact is True
    assert probe.selected_paths == ["C:/saves/current-world"]
    assert view._tab_search.content is probe


def test_lazy_search_tab_keeps_empty_context_unselected(monkeypatch) -> None:
    _SearchViewProbe.instances.clear()
    monkeypatch.setattr(
        "app.ui.views.explorer.explorer_view.EntityBlockSearchView",
        _SearchViewProbe,
    )
    view = _bare_view(None)

    view._build_search_tab()

    assert _SearchViewProbe.instances[0].selected_paths == []
