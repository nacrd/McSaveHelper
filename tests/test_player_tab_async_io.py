"""Player tab background-I/O regressions."""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.services.asset_import import AssetImportCounts
from app.services.execution_runtime import (
    CancellationToken,
    OperationCancelledError,
)
from app.ui.views.explorer.player_tab import (
    PlayerTabMixin,
    _AssetImportRequest,
)
from app.ui.views.explorer.player_tab_operations import PlayerTabOperations


class _FakeHandle:
    """允许测试控制完成时机的最小运行时句柄。"""

    def __init__(self, result: Any = None, *, complete: bool = False) -> None:
        self.cancel_calls = 0
        self.cancelled = False
        self._result = result
        self._complete = complete
        self.callback: Any = None

    def cancel(self) -> bool:
        self.cancel_calls += 1
        self.cancelled = True
        return True

    def result(self) -> Any:
        return self._result

    def add_done_callback(self, callback: Any) -> None:
        self.callback = callback
        if self._complete:
            callback(self)


class _QueuedPage:
    """记录 Flet async callable，允许测试延迟 UI 消费。"""

    def __init__(self) -> None:
        self.tasks: list[Callable[[], Coroutine[Any, Any, None]]] = []

    def run_task(
        self,
        callback: Callable[[], Coroutine[Any, Any, None]],
    ) -> None:
        self.tasks.append(callback)


def test_player_nbt_projection_reuses_background_payload() -> None:
    tab = PlayerTabMixin()
    tab.app = cast(
        Any,
        SimpleNamespace(
            translate=lambda _key, default="", **_kwargs: default,
        ),
    )
    tab.world_session = cast(
        Any,
        SimpleNamespace(
            load_player_nbt=lambda _uuid: (_ for _ in ()).throw(
                AssertionError("UI must not reload player NBT")
            ),
        ),
    )
    payload = object()

    tab._apply_player_nbt_target("player", payload)

    assert tab._current_nbt_target == "player"


def test_usercache_worker_checks_cancellation_before_io(tmp_path: Path) -> None:
    calls: list[Path] = []
    session = SimpleNamespace(
        import_usercache=lambda path: calls.append(path) or 1,
    )
    token = CancellationToken()
    token.cancel()

    with pytest.raises(OperationCancelledError):
        PlayerTabMixin._import_usercache_worker(
            session,
            tmp_path / "usercache.json",
            token,
        )

    assert calls == []


def test_asset_import_worker_uses_immutable_request(monkeypatch) -> None:
    tab = PlayerTabMixin()
    tab.app = cast(
        Any,
        SimpleNamespace(item=object(), texture=object()),
    )
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "app.ui.views.explorer.player_tab_operations.import_assets_from_sources",
        lambda **kwargs: captured.append(kwargs) or AssetImportCounts(2, 3, 1, 1),
    )
    request = _AssetImportRequest(
        paths=(Path("assets.jar"),),
        locale="zh_cn",
        configured_dir=None,
        start_path=None,
        empty_jar_results_fallback=True,
    )

    result = tab._import_assets_worker(request, CancellationToken())

    assert result == AssetImportCounts(2, 3, 1, 1)
    assert captured[0]["paths"] == (Path("assets.jar"),)


def test_new_player_load_cancels_superseded_handle() -> None:
    first_handle = _FakeHandle()
    next_handle = _FakeHandle()
    handles = iter((first_handle, next_handle))
    submitted: list[str] = []
    tab = PlayerTabMixin()
    tab.world_session = cast(Any, object())
    tab._player_service_instance = cast(Any, object())
    tab._task_scope = cast(
        Any,
        SimpleNamespace(
            submit=lambda operation, work, **kwargs: (
                submitted.append(operation) or next(handles)
            ),
        ),
    )
    tab.app = cast(
        Any,
        SimpleNamespace(
            handle_exception=lambda *_args, **_kwargs: None,
            translate=lambda _key, default="", **_kwargs: default,
        ),
    )

    tab._load_player_data("player")
    tab._load_player_data("new-player")

    assert first_handle.cancel_calls == 1
    assert submitted == ["load_player_data", "load_player_data"]


def test_player_export_uses_atomic_publish(tmp_path: Path, monkeypatch) -> None:
    output = tmp_path / "player.json"
    writes: list[tuple[Path, str]] = []
    monkeypatch.setattr(
        "app.ui.views.explorer.player_tab_operations.atomic_write_text",
        lambda path, content: writes.append((path, content)),
    )
    bundle = SimpleNamespace(to_dict=lambda: {"uuid": "player"})
    service = SimpleNamespace(
        build_export=lambda *_args, **_kwargs: bundle,
    )
    tab = PlayerTabMixin()

    result = tab._export_player_worker(
        cast(Any, service),
        object(),
        "player",
        output,
        CancellationToken(),
    )

    assert result == 1
    assert writes and writes[0][0] == output
    assert '"uuid": "player"' in writes[0][1]


def test_operations_skip_ui_callback_without_page() -> None:
    handle = _FakeHandle(4, complete=True)
    callbacks: list[int] = []
    operations = PlayerTabOperations(
        cast(
            Any,
            SimpleNamespace(submit=lambda *_args, **_kwargs: handle),
        ),
        get_page=lambda: None,
        get_world_session=lambda: cast(Any, object()),
        get_current_uuid=lambda: None,
    )

    operations.submit_asset_import(
        _AssetImportRequest((), "zh_cn", None, None),
        object(),
        object(),
        cast(Any, callbacks.append),
        lambda error: pytest.fail(str(error)),
    )

    assert callbacks == []


def test_operations_close_drops_queued_ui_callback() -> None:
    handle = _FakeHandle(AssetImportCounts(1, 0, 0, 1), complete=True)
    page = _QueuedPage()
    callbacks: list[AssetImportCounts] = []
    operations = PlayerTabOperations(
        cast(
            Any,
            SimpleNamespace(submit=lambda *_args, **_kwargs: handle),
        ),
        get_page=lambda: cast(Any, page),
        get_world_session=lambda: None,
        get_current_uuid=lambda: None,
    )

    operations.submit_asset_import(
        _AssetImportRequest((), "zh_cn", None, None),
        object(),
        object(),
        callbacks.append,
        lambda error: pytest.fail(str(error)),
    )
    operations.close()
    asyncio.run(page.tasks.pop()())

    assert callbacks == []
