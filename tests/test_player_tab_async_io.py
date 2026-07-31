"""Player tab background-I/O regressions."""
from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Coroutine
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.presenters.nbt_view_state import NbtViewState
from app.services.asset_import import AssetImportCounts
from app.services.execution_runtime import (
    CancellationToken,
    ExecutionRuntime,
    LaneLimits,
    OperationCancelledError,
)
from app.services.player.models import PlayerRef
from app.ui.views.explorer.player_tab import (
    PlayerTabMixin,
    _AssetImportRequest,
)
from app.ui.views.explorer.player_tab_operations import (
    NameLookupResult,
    PlayerTabOperations,
    resolve_player_names_online,
)


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
    tab._nbt_view_state = NbtViewState()
    payload = object()

    tab._apply_player_nbt_target("player", payload)

    assert tab._nbt_view_state.target == "player"


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
    tab._nbt_view_state = NbtViewState()
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


def test_operations_invalidate_drops_old_ui_and_accepts_next_world() -> None:
    old_handle = _FakeHandle(AssetImportCounts(1, 0, 0, 1), complete=True)
    new_handle = _FakeHandle(AssetImportCounts(0, 2, 1, 1), complete=True)
    handles = iter((old_handle, new_handle))
    page = _QueuedPage()
    callbacks: list[AssetImportCounts] = []
    operations = PlayerTabOperations(
        cast(
            Any,
            SimpleNamespace(submit=lambda *_args, **_kwargs: next(handles)),
        ),
        get_page=lambda: cast(Any, page),
        get_world_session=lambda: None,
        get_current_uuid=lambda: None,
    )
    request = _AssetImportRequest((), "zh_cn", None, None)

    operations.submit_asset_import(
        request,
        object(),
        object(),
        callbacks.append,
        lambda error: pytest.fail(str(error)),
    )
    operations.invalidate()
    operations.submit_asset_import(
        request,
        object(),
        object(),
        callbacks.append,
        lambda error: pytest.fail(str(error)),
    )
    asyncio.run(page.tasks.pop(0)())
    asyncio.run(page.tasks.pop(0)())

    assert old_handle.cancel_calls == 0
    assert callbacks == [AssetImportCounts(0, 2, 1, 1)]


def test_reset_player_selection_clears_previous_world_projection() -> None:
    cleared_grids: list[list[object]] = []
    hud_resets: list[bool] = []
    field = SimpleNamespace(value="old", update=lambda: None)
    tab = PlayerTabMixin()
    tab.current_uuid = "old-player"
    tab._current_player_data = object()
    tab._player_hud = cast(
        Any,
        SimpleNamespace(reset=lambda: hud_resets.append(True)),
    )
    grid = cast(
        Any,
        SimpleNamespace(
            set_inventory=lambda items: cleared_grids.append(items),
        ),
    )
    tab._inventory = grid
    tab._ender_inventory = grid
    tab._container_preview_grid = grid
    tab._player_edit_fields = {"Health": field}

    tab._reset_player_selection()

    assert tab.current_uuid is None
    assert tab._current_player_data is None
    assert hud_resets == [True]
    assert cleared_grids == [[], [], []]
    assert field.value == ""


def test_player_export_drops_callback_after_switching_player() -> None:
    handle = _FakeHandle(1, complete=True)
    page = _QueuedPage()
    session = object()
    current_uuid = ["old-player"]
    callbacks: list[Path] = []
    operations = PlayerTabOperations(
        cast(
            Any,
            SimpleNamespace(submit=lambda *_args, **_kwargs: handle),
        ),
        get_page=lambda: cast(Any, page),
        get_world_session=lambda: cast(Any, session),
        get_current_uuid=lambda: current_uuid[0],
    )

    operations.submit_player_export(
        cast(Any, object()),
        cast(Any, session),
        "old-player",
        Path("old-player.txt"),
        lambda _key, default="", **_kwargs: default,
        callbacks.append,
        lambda error: pytest.fail(str(error)),
    )
    current_uuid[0] = "new-player"
    asyncio.run(page.tasks.pop()())

    assert callbacks == []


class _ResolvingUuidService:
    """返回预置当前名的 UUID 服务替身。"""

    def __init__(self) -> None:
        self.uuids: list[str] = []
        self.names_by_uuid: dict[str, str] = {
            "22222222222222222222222222222222": "Alex",
        }

    def query_current_name(
        self,
        uuid: str,
        log_callback: object = None,
    ) -> str | None:
        del log_callback
        self.uuids.append(uuid)
        return self.names_by_uuid.get(uuid)


def _lookup_runtime() -> ExecutionRuntime:
    """创建名称解析测试用共享运行时（IO 4 worker）。"""
    limits = LaneLimits(max_workers=4, queue_capacity=16)
    return ExecutionRuntime(io_limits=limits, cpu_limits=limits)


def test_name_lookup_worker_resolves_and_reports_unresolved() -> None:
    runtime = _lookup_runtime()
    uuid_service = _ResolvingUuidService()
    try:
        result = resolve_player_names_online(
            runtime,
            uuid_service,
            [
                "11111111111111111111111111111111",  # 未找到
                "22222222222222222222222222222222",  # 解析为 Alex
                "33333333333333333333333333333333",  # 未找到
            ],
            CancellationToken(),
        )
    finally:
        runtime.shutdown(wait=True)

    assert result == NameLookupResult(
        resolved={"22222222222222222222222222222222": "Alex"},
        unresolved=(
            "11111111111111111111111111111111",
            "33333333333333333333333333333333",
        ),
    )
    assert uuid_service.uuids == [
        "11111111111111111111111111111111",
        "22222222222222222222222222222222",
        "33333333333333333333333333333333",
    ]


def test_name_lookup_worker_checks_cancellation_between_queries() -> None:
    runtime = _lookup_runtime()
    uuid_service = _ResolvingUuidService()
    token = CancellationToken()
    token.cancel()
    try:
        with pytest.raises(OperationCancelledError):
            resolve_player_names_online(
                runtime,
                uuid_service,
                ["22222222222222222222222222222222"],
                token,
            )
    finally:
        runtime.shutdown(wait=True)

    assert uuid_service.uuids == []


def test_name_lookup_delivers_result_for_current_session() -> None:
    handle = _FakeHandle(
        NameLookupResult(
            resolved={"22222222222222222222222222222222": "Alex"},
            unresolved=(),
        ),
        complete=True,
    )
    page = _QueuedPage()
    session = object()
    callbacks: list[NameLookupResult] = []
    operations = PlayerTabOperations(
        cast(
            Any,
            SimpleNamespace(submit=lambda *_args, **_kwargs: handle),
        ),
        get_page=lambda: cast(Any, page),
        get_world_session=lambda: cast(Any, session),
        get_current_uuid=lambda: None,
    )

    operations.submit_name_lookup(
        cast(Any, object()),  # 假作用域不执行 work，runtime 未使用
        cast(Any, session),
        _ResolvingUuidService(),
        ["22222222222222222222222222222222"],
        callbacks.append,
        lambda error: pytest.fail(str(error)),
    )
    asyncio.run(page.tasks.pop()())

    assert callbacks == [
        NameLookupResult(
            resolved={"22222222222222222222222222222222": "Alex"},
            unresolved=(),
        )
    ]


def test_name_lookup_drops_callback_after_world_switch() -> None:
    handle = _FakeHandle(
        NameLookupResult(
            resolved={"22222222222222222222222222222222": "Alex"},
            unresolved=(),
        ),
        complete=True,
    )
    page = _QueuedPage()
    session = object()
    current_session: list[Any] = [session]
    callbacks: list[NameLookupResult] = []
    operations = PlayerTabOperations(
        cast(
            Any,
            SimpleNamespace(submit=lambda *_args, **_kwargs: handle),
        ),
        get_page=lambda: cast(Any, page),
        get_world_session=lambda: current_session[0],
        get_current_uuid=lambda: None,
    )

    operations.submit_name_lookup(
        cast(Any, object()),  # 假作用域不执行 work，runtime 未使用
        cast(Any, session),
        _ResolvingUuidService(),
        ["22222222222222222222222222222222"],
        callbacks.append,
        lambda error: pytest.fail(str(error)),
    )
    current_session[0] = object()  # 世界已切换
    asyncio.run(page.tasks.pop()())

    assert callbacks == []


class _RunWorkScope:
    """提交时立即执行工作函数，并返回已完成句柄。"""

    def __init__(self) -> None:
        self.work: Any = None

    def submit(
        self,
        operation: str,
        work: Any,
        **kwargs: Any,
    ) -> _FakeHandle:
        del operation, kwargs
        self.work = work
        result = work(CancellationToken())
        return _FakeHandle(result, complete=True)


def test_lookup_player_names_online_queries_unknown_and_seeds_session() -> None:
    known = PlayerRef(
        uuid_norm="11111111111111111111111111111111",
        uuid_hyphen="11111111-1111-1111-1111-111111111111",
        name="Known",
    )
    unknown = PlayerRef(
        uuid_norm="22222222222222222222222222222222",
        uuid_hyphen="22222222-2222-2222-2222-222222222222",
        name=None,
    )
    seeded: list[dict[str, str]] = []
    session = SimpleNamespace(seed_player_names=seeded.append)
    uuid_service = _ResolvingUuidService()
    page = _QueuedPage()
    refreshed: list[bool] = []
    runtime = _lookup_runtime()
    tab = PlayerTabMixin()
    tab.app = cast(
        Any,
        SimpleNamespace(
            execution_runtime=runtime,
            uuid=uuid_service,
            page=cast(Any, page),
            translate=lambda _key, default="", **_kwargs: default,
            handle_exception=lambda *_args, **_kwargs: None,
        ),
    )
    tab.world_session = cast(Any, session)
    tab._player_refs_cache = [known, unknown]
    tab._task_scope = cast(Any, _RunWorkScope())
    tab._refresh_player_list = lambda: refreshed.append(True)  # type: ignore[method-assign]
    try:
        tab._lookup_player_names_online()
        for task in page.tasks:
            asyncio.run(task())
    finally:
        runtime.shutdown(wait=True)

    assert uuid_service.uuids == ["22222222222222222222222222222222"]
    assert seeded == [{"22222222222222222222222222222222": "Alex"}]
    assert refreshed == [True]
    assert tab._name_lookup_pending is False


def test_lookup_player_names_online_skips_when_all_names_known() -> None:
    known = PlayerRef(
        uuid_norm="11111111111111111111111111111111",
        uuid_hyphen="11111111-1111-1111-1111-111111111111",
        name="Known",
    )
    uuid_service = _ResolvingUuidService()
    tab = PlayerTabMixin()
    tab.app = cast(
        Any,
        SimpleNamespace(
            uuid=uuid_service,
            page=object(),
            translate=lambda _key, default="", **_kwargs: default,
            handle_exception=lambda *_args, **_kwargs: None,
        ),
    )
    tab.world_session = cast(Any, object())
    tab._player_refs_cache = [known]

    tab._lookup_player_names_online()

    assert uuid_service.uuids == []
    assert getattr(tab, "_name_lookup_pending", False) is False


def test_auto_lookup_queries_unknown_once_per_world() -> None:
    known = PlayerRef(
        uuid_norm="11111111111111111111111111111111",
        uuid_hyphen="11111111-1111-1111-1111-111111111111",
        name="Known",
    )
    unresolved = PlayerRef(
        uuid_norm="33333333333333333333333333333333",
        uuid_hyphen="33333333-3333-3333-3333-333333333333",
        name=None,
    )
    seeded: list[dict[str, str]] = []
    session = SimpleNamespace(seed_player_names=seeded.append)
    uuid_service = _ResolvingUuidService()  # 只解析 2222...
    page = _QueuedPage()
    runtime = _lookup_runtime()
    tab = PlayerTabMixin()
    tab.app = cast(
        Any,
        SimpleNamespace(
            execution_runtime=runtime,
            uuid=uuid_service,
            page=cast(Any, page),
            translate=lambda _key, default="", **_kwargs: default,
            handle_exception=lambda *_args, **_kwargs: None,
        ),
    )
    tab.world_session = cast(Any, session)
    tab._player_refs_cache = [known, unresolved]
    tab._task_scope = cast(Any, _RunWorkScope())
    tab._refresh_player_list = lambda: None  # type: ignore[method-assign]
    try:
        # 第一次打开玩家栏：查询全部未知名玩家（1111 已有名，3333 未解析）
        tab._auto_lookup_unknown_names()
        for task in page.tasks:
            asyncio.run(task())
        assert uuid_service.uuids == ["33333333333333333333333333333333"]

        # 第二次触发：3333 已尝试且失败，不应重复查询
        tab._auto_lookup_unknown_names()
        assert uuid_service.uuids == ["33333333333333333333333333333333"]
        assert tab._name_lookup_pending is False
    finally:
        runtime.shutdown(wait=True)


def test_auto_lookup_resolves_and_then_skips_known_players() -> None:
    unknown = PlayerRef(
        uuid_norm="22222222222222222222222222222222",
        uuid_hyphen="22222222-2222-2222-2222-222222222222",
        name=None,
    )
    seeded: list[dict[str, str]] = []
    session = SimpleNamespace(seed_player_names=seeded.append)
    uuid_service = _ResolvingUuidService()
    page = _QueuedPage()
    runtime = _lookup_runtime()
    tab = PlayerTabMixin()
    tab.app = cast(
        Any,
        SimpleNamespace(
            execution_runtime=runtime,
            uuid=uuid_service,
            page=cast(Any, page),
            translate=lambda _key, default="", **_kwargs: default,
            handle_exception=lambda *_args, **_kwargs: None,
        ),
    )
    tab.world_session = cast(Any, session)
    tab._player_refs_cache = [unknown]
    tab._task_scope = cast(Any, _RunWorkScope())
    tab._refresh_player_list = lambda: None  # type: ignore[method-assign]
    try:
        tab._auto_lookup_unknown_names()
        for task in page.tasks:
            asyncio.run(task())

        assert seeded == [{"22222222222222222222222222222222": "Alex"}]

        # 名称已解析到会话；再次触发不再查询
        tab._player_refs_cache = [
            PlayerRef(
                uuid_norm="22222222222222222222222222222222",
                uuid_hyphen="22222222-2222-2222-2222-222222222222",
                name="Alex",
            )
        ]
        tab._auto_lookup_unknown_names()
        assert uuid_service.uuids == ["22222222222222222222222222222222"]
    finally:
        runtime.shutdown(wait=True)


def test_name_lookup_worker_runs_queries_in_parallel() -> None:
    """3 个查询应同时开始（有界并发），而非串行排队。"""
    started = threading.Event()
    release = threading.Event()
    started_count: list[str] = []
    state_lock = threading.Lock()

    class _BlockingCurrentNameService:
        def query_current_name(
            self,
            uuid: str,
            log_callback: object = None,
        ) -> str:
            del log_callback
            with state_lock:
                started_count.append(uuid)
                if len(started_count) == 3:
                    started.set()
            if not release.wait(timeout=2):
                raise TimeoutError("查询未获准继续")
            return "name"

    service = _BlockingCurrentNameService()
    holder: dict[str, NameLookupResult] = {}
    runtime = _lookup_runtime()

    def run_worker() -> None:
        holder["result"] = resolve_player_names_online(
            runtime,
            service,
            ["1" * 32, "2" * 32, "3" * 32],
            CancellationToken(),
        )

    worker = threading.Thread(target=run_worker)
    worker.start()
    try:
        # 未释放前 3 个查询都已开始 → 证明并行执行
        assert started.wait(timeout=2)
        assert len(started_count) == 3
        release.set()
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert holder["result"].resolved == {
            "1" * 32: "name",
            "2" * 32: "name",
            "3" * 32: "name",
        }
    finally:
        release.set()
        worker.join(timeout=2)
        runtime.shutdown(wait=True)
