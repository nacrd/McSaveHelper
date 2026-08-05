"""Qt 玩家头像与名称解析相关测试。"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator, cast

import pytest
from PySide6.QtGui import QPixmap

from app.qtui.views.player import QtPlayerPanel
from app.qtui.views.player_editor import QtPlayerEditor
from app.qtui.views.player_tasks import NameLookupResult, PlayerTasks
from app.services.execution_runtime import ExecutionRuntime, LaneLimits
from app.services.item_service import ItemService
from app.services.player.models import PlayerRef
from app.services.player_service import PlayerService


@pytest.fixture
def panel(qt_app: object) -> Iterator[QtPlayerPanel]:
    del qt_app
    view = QtPlayerPanel(
        lambda key, default="", **kw: default.format(**kw),
        lambda _uuid: None,
        lambda: None,
        lambda: None,
        lambda: None,
        lambda: None,
        item_service=ItemService(),
        player_service=PlayerService(),
    )
    yield view
    view.dispose()


def test_apply_resolved_names_updates_list(panel: QtPlayerPanel) -> None:
    refs = (
        PlayerRef(
            uuid_norm="a" * 32,
            uuid_hyphen="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            name=None,
        ),
        PlayerRef(
            uuid_norm="b" * 32,
            uuid_hyphen="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            name="Steve",
        ),
    )
    panel.show_players(refs)
    assert "未知玩家" in panel._list.item(0).text()
    panel.apply_resolved_names({"a" * 32: "Alex"})
    assert "Alex" in panel._list.item(0).text()
    assert panel.player_refs[0].name == "Alex"
    assert panel.player_refs[1].name == "Steve"


def test_editor_set_avatar_path_uses_pixmap_or_initial(
    qt_app: object,
    tmp_path: Path,
) -> None:
    del qt_app
    editor = QtPlayerEditor(
        lambda key, default="", **kw: default.format(**kw),
        lambda: None,
        lambda: None,
        lambda: None,
        lambda: None,
    )
    editor.set_avatar_path(None, initial="alex")
    assert editor._avatar.text() == "A"
    image = tmp_path / "face.png"
    pix = QPixmap(32, 32)
    pix.fill()
    assert pix.save(str(image), "PNG")
    editor.set_avatar_path(str(image), initial="z")
    assert editor._avatar.pixmap() is not None
    assert not editor._avatar.pixmap().isNull()
    assert editor._avatar.text() == ""
    editor.dispose()


def test_name_lookup_result_shape() -> None:
    result = NameLookupResult(
        resolved={"a" * 32: "Alex"},
        unresolved=("b" * 32,),
    )
    assert result.resolved["a" * 32] == "Alex"
    assert result.unresolved == ("b" * 32,)


def test_player_tasks_usercache_success(tmp_path: Path, qt_app: object) -> None:
    del qt_app
    import time
    from PySide6.QtWidgets import QApplication

    runtime = ExecutionRuntime(
        io_limits=LaneLimits(max_workers=2, queue_capacity=8),
        cpu_limits=LaneLimits(max_workers=2, queue_capacity=8),
    )
    events: list[str] = []

    class _Session:
        def __init__(self) -> None:
            self.world_path = tmp_path / "world"
            self.world_path.mkdir()

        def import_usercache(self, path: Path) -> int:
            assert path.name.endswith(".json")
            return 2

    class _CB:
        players_ready = staticmethod(lambda *a: None)
        players_error = staticmethod(lambda *a: None)
        detail_ready = staticmethod(lambda *a: None)
        detail_error = staticmethod(lambda *a: None)
        export_success = staticmethod(lambda *a: None)
        export_error = staticmethod(lambda *a: None)
        usercache_success = staticmethod(
            lambda imported, gen: events.append(f"uc:{imported}:{gen}")
        )
        usercache_error = staticmethod(lambda *a: events.append("uc-err"))
        name_lookup_success = staticmethod(lambda *a: None)
        name_lookup_error = staticmethod(lambda *a: None)

    session = _Session()
    tasks = PlayerTasks(
        runtime,
        PlayerService(),
        cast(object, _CB()),
    )
    tasks._session = session  # type: ignore[assignment]
    tasks._world_generation = 1
    cache = tmp_path / "usercache.json"
    cache.write_text("[]", encoding="utf-8")
    assert tasks.import_usercache(session, cache) is True
    app = QApplication.instance()
    assert app is not None
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and not events:
        app.processEvents()
        time.sleep(0.02)
    tasks.close()
    runtime.shutdown(wait=True, timeout=3.0)
    assert any(e.startswith("uc:2:") for e in events)


def test_resolve_names_direct() -> None:
    class _Uuid:
        @staticmethod
        def query_current_name(uuid: str, log_callback=None):
            del log_callback
            return "Alex" if uuid.startswith("a") else None

    class _Context:
        is_cancelled = False

        def raise_if_cancelled(self) -> None:
            return None

    runtime = ExecutionRuntime(
        io_limits=LaneLimits(max_workers=2, queue_capacity=8),
        cpu_limits=LaneLimits(max_workers=2, queue_capacity=8),
    )
    tasks = PlayerTasks(
        runtime,
        PlayerService(),
        cast(
            object,
            type(
                "CB",
                (),
                {
                    "players_ready": staticmethod(lambda *a: None),
                    "players_error": staticmethod(lambda *a: None),
                    "detail_ready": staticmethod(lambda *a: None),
                    "detail_error": staticmethod(lambda *a: None),
                    "export_success": staticmethod(lambda *a: None),
                    "export_error": staticmethod(lambda *a: None),
                    "usercache_success": staticmethod(lambda *a: None),
                    "usercache_error": staticmethod(lambda *a: None),
                    "name_lookup_success": staticmethod(lambda *a: None),
                    "name_lookup_error": staticmethod(lambda *a: None),
                },
            )(),
        ),
    )
    result = tasks._resolve_names(
        cast(object, _Uuid()),
        ["a" * 32, "b" * 32],
        cast(object, _Context()),
    )
    tasks.close()
    runtime.shutdown(wait=True, timeout=3.0)
    assert result.resolved == {"a" * 32: "Alex"}
    assert result.unresolved == ("b" * 32,)
