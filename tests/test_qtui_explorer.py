"""Qt Explorer 世界信息切片的异步与生命周期测试。"""
from __future__ import annotations

import time
from threading import Event
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, cast

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from app.services.item_service import ItemService
from app.services.cache_registry import CacheRegistry
from app.services.uuid_service import UUIDService
from app.services.player_service import PlayerService
from app.services.entity_block_search.models import SearchResult
from app.qtui.views.explorer import (
    ExplorerHost,
    ExplorerView,
    map_index_progress,
)
from app.qtui.views.explorer_tasks import ExplorerWorldSnapshot
from app.qtui.views.player_tasks import PlayerDetailResult
from app.services.backup_service import BackupRecord
from app.services.execution_runtime import ExecutionRuntime, LaneLimits
from app.services.nbt_commit_service import NbtCommitResult
from app.services.world_stats_service import (
    BlockStats,
    DimensionSizeStats,
    EntityStats,
    PlayerPlaytimeStats,
    WorldStatistics,
    WorldStatsCancelledError,
)
from app.services.world_transaction import (
    WorldTransactionCancelledError,
    WorldTransactionResult,
)
from core.omni.models import WorldInfo
from core.nbt import (
    Compound,
    Double,
    File,
    Float,
    Int,
    List as NbtList,
    String,
)
from core.world_index import WorldShellMetadata
from core.world_index_progress import (
    WorldIndexBuildPhase,
    WorldIndexProgressFrame,
)


def _wait_until(
    predicate: Callable[[], bool],
    timeout_s: float = 5.0,
) -> bool:
    """处理 Qt 事件直到条件成立或超时。"""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app = QApplication.instance()
        if app is not None:
            app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


class _Session:
    """Explorer 首屏读取所需的会话投影。"""

    def __init__(self, world_path: Path) -> None:
        self.world_path = world_path
        self.player_uuid = "11111111222233334444555555555555"
        self.player_data = Compound({
            "Health": Float(18.0),
            "foodLevel": Int(16),
            "XpLevel": Int(7),
            "Dimension": String("minecraft:overworld"),
            "playerGameType": Int(0),
            "Pos": NbtList[Double]([10.0, 64.0, -3.0]),
        })

    def get_dimensions(self) -> list[dict[str, object]]:
        region_dir = self.world_path / "region"
        region_dir.mkdir(parents=True, exist_ok=True)
        return [{
            "id": "overworld",
            "name": "主世界",
            "region_dir": str(region_dir),
            "coordinate_scale": 1.0,
        }]

    def get_player_uuids(self) -> list[str]:
        return [self.player_uuid]

    def get_player_names(self) -> dict[str, str]:
        return {self.player_uuid: "Alex"}

    @staticmethod
    def get_known_player_name(_uuid: str) -> str:
        return "Alex"

    def get_player_file_path(self, uuid: str) -> Path:
        return self.world_path / "playerdata" / f"{uuid}.dat"

    def get_player_data(self, _uuid: str) -> Compound:
        return self.player_data

    def load_player_data(self, uuid: str) -> Compound:
        return self.get_player_data(uuid)

    def load_chunk_nbt(
        self,
        region_path: Path,
        chunk_x: int,
        chunk_z: int,
    ) -> tuple[Compound, Path] | None:
        absolute = self.world_path / region_path
        if not absolute.is_file():
            return None
        from core.mca import RegionFile

        with RegionFile.open(absolute) as region:
            if not region.has_chunk(chunk_x, chunk_z):
                return None
            data = region.read_chunk(chunk_x, chunk_z)
        return data, absolute

    @staticmethod
    def get_world_info() -> WorldInfo:
        return WorldInfo(
            version=3953,
            version_name="1.21",
            level_name="Demo World",
            game_type=0,
        )


class _ReadContext:
    """同步返回确定索引和会话的仓库读取上下文。"""

    def __init__(self, world_path: Path) -> None:
        if not (world_path / "level.dat").exists():
            File({
                "Data": Compound({
                    "LevelName": String("Demo World"),
                    "GameType": Int(0),
                }),
            }).save(world_path / "level.dat")
        self.shell = WorldShellMetadata(
            world_path=world_path,
            display_name="Demo World",
            has_level_dat=True,
            overworld_region_count=2,
            dimension_hint_count=1,
        )
        self._world_path = world_path

    def get_index_progressive(
        self,
        *,
        cancel_check: Callable[[], bool],
        progress_callback: Callable[[WorldIndexProgressFrame], None],
    ) -> object:
        assert cancel_check() is False
        progress_callback(WorldIndexProgressFrame(
            self._world_path,
            WorldIndexBuildPhase.PROBING,
            completed=1,
            total=2,
            discovered_files=3,
            stamped_files=1,
        ))
        return type("Snapshot", (), {
            "region_files": (Path("r.0.0.mca"), Path("r.0.1.mca")),
        })()

    def open_session_with_index(
        self,
        snapshot: object,
        *,
        log: Callable[[str, str], None],
    ) -> _Session:
        del snapshot, log
        return _Session(self._world_path)


class _Repository:
    """记录世界打开请求的读取仓库。"""

    def __init__(self) -> None:
        self.opened: list[Path] = []
        self.error: Exception | None = None
        self.index_requests: list[Path] = []

    def open(self, world_path: Path) -> _ReadContext:
        self.opened.append(world_path)
        if self.error is not None:
            raise self.error
        return _ReadContext(world_path)

    def get_index(self, world_path: Path) -> object:
        self.index_requests.append(world_path)
        return object()


class _WorldStats:
    """提供确定统计结果和可控取消点。"""

    def __init__(self) -> None:
        self.calls: list[Path] = []
        self.should_block = False
        self.started = Event()
        self.release = Event()
        self.completed = Event()

    def analyze_world(
        self,
        world_path: Path,
        progress_callback: Callable[[float, str], None],
        name_map: dict[str, str | None],
        index_snapshot: object,
        cancel_check: Callable[[], bool],
    ) -> WorldStatistics:
        assert index_snapshot is not None
        assert name_map
        self.calls.append(world_path)
        progress_callback(0.15, "regions:0:2")
        if self.should_block:
            self.started.set()
            self.release.wait(2.0)
        if cancel_check():
            self.completed.set()
            raise WorldStatsCancelledError("cancelled")
        progress_callback(1.0, "done")
        result = WorldStatistics(
            total_regions=2,
            total_blocks=120,
            total_entities=4,
            block_stats=BlockStats(
                total_count=120,
                top_blocks=[("minecraft:stone", 100)],
            ),
            entity_stats=EntityStats(
                total_count=4,
                top_entities=[("minecraft:zombie", 4)],
            ),
            region_sizes={"region/r.0.0.mca": 2048},
            loaded_chunks=3,
            empty_chunks=1,
            dimension_stats=[DimensionSizeStats(
                "overworld", "Overworld", 2, 2048
            )],
            player_stats=[PlayerPlaytimeStats(
                "11111111222233334444555555555555",
                "Alex",
                72000,
                90000,
                deaths=2,
                mob_kills=8,
                mined=30,
                placed=12,
            )],
        )
        self.completed.set()
        return result


class _Backup:
    """返回确定恢复点记录的备份服务。"""

    def __init__(self) -> None:
        self.calls: list[Path] = []

    def create_backup(
        self,
        world_path: Path,
        label: str,
        progress_callback: Callable[[float, str], None],
        cancel_check: Callable[[], bool],
    ) -> BackupRecord:
        assert label == "Explorer 快速备份"
        assert cancel_check() is False
        self.calls.append(world_path)
        progress_callback(0.5, "copying")
        return BackupRecord(
            backup_id="20260731T000000Z-12345678",
            label=label,
            world_name=world_path.name,
            source_path=str(world_path),
            created_at=datetime.now(timezone.utc),
            size_bytes=10,
            file_count=1,
            backup_path=world_path.parent / "backup",
        )


class _WorldTransactions:
    """在原世界上直接执行 mutation，避免真实暂存/备份 I/O。"""

    def __init__(self) -> None:
        self.calls: list[tuple[Path, str]] = []

    def mutate(
        self,
        world_path: Path | str,
        mutation: Callable[[Path], bool],
        *,
        backup_label: str,
        cancel_check: Callable[[], bool] | None = None,
        validator: object = None,
    ) -> WorldTransactionResult[bool]:
        del validator
        world = Path(world_path)
        self.calls.append((world, backup_label))
        if cancel_check is not None and cancel_check():
            raise WorldTransactionCancelledError("cancelled")
        value = mutation(world)
        return WorldTransactionResult(
            value=value,
            world_path=world,
            backup=BackupRecord(
                backup_id="20260805T000000Z-region",
                label=backup_label,
                world_name=world.name,
                source_path=str(world),
                created_at=datetime.now(timezone.utc),
                size_bytes=1,
                file_count=1,
                backup_path=world.parent / "region-delete-backup.zip",
            ),
        )


class _SaveContext:
    def __init__(self) -> None:
        self.pick_calls = 0

    def on_import_save(self) -> None:
        self.pick_calls += 1


class _ViewManager:
    def __init__(self) -> None:
        self.switched: list[str] = []

    def switch_view(self, view_id: str) -> None:
        self.switched.append(view_id)


class FakeHost:
    """ExplorerHost 的隔离 Qt 测试实现。"""

    def __init__(self) -> None:
        limits = LaneLimits(max_workers=2, queue_capacity=8)
        self.runtime = ExecutionRuntime(io_limits=limits, cpu_limits=limits)
        self.repository = _Repository()
        self.stats_service = _WorldStats()
        self.backup_service = _Backup()
        self.transactions = _WorldTransactions()
        self.item_service = ItemService()
        self.texture_service = None
        self.uuid_service = UUIDService()
        self.cache_reg = CacheRegistry()
        self.save_context = _SaveContext()
        self.views = _ViewManager()
        self.current_path: str | None = None
        self.progress: list[tuple[str, float]] = []
        self.infos: list[tuple[str, str]] = []
        self.warns: list[tuple[str, str]] = []
        self.errors: list[tuple[str, str]] = []
        self.save_path: str | None = None

    def translate(self, key: str, default: str = "", **kwargs: Any) -> str:
        del key
        return default.format(**kwargs)

    def log(self, msg: str, level: str = "INFO") -> None:
        del msg, level

    def show_progress(self, task_name: str = "") -> None:
        self.progress.append((task_name, 0.0))

    def hide_progress(self) -> None:
        self.progress.append(("hide", 0.0))

    def update_progress_with_task(self, task_name: str, value: float) -> None:
        self.progress.append((task_name, value))

    def info_dialog(self, title: str, message: str) -> None:
        self.infos.append((title, message))

    def warn_dialog(self, title: str, message: str) -> None:
        self.warns.append((title, message))

    def error_dialog(
        self,
        title: str,
        message: str,
        exception: Exception | None = None,
        show_details: bool = False,
    ) -> None:
        del exception, show_details
        self.errors.append((title, message))

    def handle_exception(
        self,
        exception: Exception,
        title: str | None = None,
        log: bool = True,
        show_dialog: bool = True,
    ) -> None:
        del log, show_dialog
        self.errors.append((title or "异常", str(exception)))

    def save_file(
        self,
        title: str = "",
        default_ext: str = ".txt",
        file_types: list[tuple[str, str]] | None = None,
    ) -> str | None:
        del title, default_ext, file_types
        return self.save_path

    @property
    def execution_runtime(self) -> ExecutionRuntime:
        return self.runtime

    @property
    def world_repository(self) -> object:
        return self.repository

    @property
    def world_stats(self) -> object:
        return self.stats_service

    @property
    def backup(self) -> object:
        return self.backup_service

    @property
    def world_transactions(self) -> object:
        return self.transactions

    @property
    def item(self) -> object:
        return self.item_service

    @property
    def texture(self) -> object:
        return self.texture_service

    @property
    def uuid(self) -> object:
        return self.uuid_service

    @property
    def cache_registry(self) -> object:
        return self.cache_reg

    def pick_file(
        self,
        title: str = "",
        file_types: list[tuple[str, str]] | None = None,
    ) -> str | None:
        del title, file_types
        return getattr(self, "picked_file", None)

    @property
    def save_context_manager(self) -> object:
        return self.save_context

    @property
    def view_manager(self) -> object:
        return self.views

    @property
    def current_save_path(self) -> str | None:
        return self.current_path

    def close(self) -> None:
        self.cache_reg.close()
        self.runtime.shutdown(wait=True, timeout=5.0)


@pytest.fixture
def host(qt_app: object) -> Iterator[FakeHost]:
    del qt_app
    fake = FakeHost()
    yield fake
    fake.close()


@pytest.fixture
def view(host: FakeHost) -> Iterator[ExplorerView]:
    explorer = ExplorerView(cast(ExplorerHost, host))
    yield explorer
    explorer.dispose()


def test_explorer_enables_migrated_tabs(
    view: ExplorerView,
) -> None:
    assert view._tabs.count() == 6
    assert view._tabs.isTabEnabled(0)
    assert view._tabs.isTabEnabled(1)
    assert view._tabs.isTabEnabled(2)
    assert view._tabs.isTabEnabled(3)
    assert view._tabs.isTabEnabled(4)
    assert view._tabs.isTabEnabled(5)
    assert view.get_top_actions() == []


def test_world_load_projects_info_and_deduplicates_path(
    view: ExplorerView,
    host: FakeHost,
    tmp_path: Path,
) -> None:
    view.on_save_selected(str(tmp_path))

    assert _wait_until(lambda: view.world_session is not None)
    labels = [label.text() for label in view.findChildren(QLabel)]
    assert "Demo World" in labels
    assert "1.21（ID: 3953）" in labels
    assert any(value == 76.0 for _label, value in host.progress)
    assert host.repository.opened == [tmp_path.resolve()]

    view.on_save_selected(str(tmp_path))
    assert host.repository.opened == [tmp_path.resolve()]


def test_world_load_projects_player_list_and_summary(
    view: ExplorerView,
    tmp_path: Path,
) -> None:
    view.on_save_selected(str(tmp_path))

    assert _wait_until(lambda: view._players.list_state.total_count == 1)
    assert _wait_until(
        lambda: "Alex" in view._players.editor.summary_text()
    )
    assert view._players.current_uuid == (
        "11111111222233334444555555555555"
    )
    summary = view._players.editor.summary_text()
    assert "18" in summary
    assert "minecraft:overworld" in summary
    assert view._players.editor.player_data is not None
    assert view._players.editor._fields["Health"].text() != ""

    view._players._filter.setText("missing")
    assert view._players.list_state.total_count == 0
    view._players._filter.setText("Alex")
    assert view._players.list_state.total_count == 1


def test_region_map_scan_projects_regions_and_search(
    view: ExplorerView,
    tmp_path: Path,
) -> None:
    region_dir = tmp_path / "region"
    region_dir.mkdir(parents=True, exist_ok=True)
    (region_dir / "r.0.0.mca").write_bytes(b"0" * 2048)
    (region_dir / "r.1.0.mca").write_bytes(b"1" * 4096)

    view.on_save_selected(str(tmp_path))
    assert _wait_until(lambda: view.world_session is not None)
    coordinator = view._region_map
    panel = coordinator.panel

    assert _wait_until(lambda: len(panel.canvas._regions) == 2)
    assert panel.current_dimension_id == "overworld"
    assert "2" in panel._stats.text()

    panel.canvas.select_region((0, 0))
    assert coordinator.selected_region == (0, 0)
    assert "r.0.0.mca" in panel._status.text()

    coordinator._on_search("r.1.0")
    assert panel.canvas.selected_region == (1, 0)


def test_region_map_markers_add_and_delete(
    view: ExplorerView,
    host: FakeHost,
    tmp_path: Path,
) -> None:
    from app.services.map_marker_service import MapMarkerService

    world = tmp_path / "world"
    world.mkdir()
    region_dir = world / "region"
    region_dir.mkdir(parents=True, exist_ok=True)
    (region_dir / "r.0.0.mca").write_bytes(b"0" * 1024)
    # 标记仓库必须在存档目录之外。
    marker_root = tmp_path / "marker_store"
    marker_root.mkdir()
    # 用临时根目录替换控制器里的标记服务，避免写用户主目录。
    view._region_map._map_controller.close()
    view._region_map._marker_scope.close()
    view._region_map._marker_scope = host.runtime.create_scope(
        "qt_region_map_markers_test"
    )
    from app.controllers.map_controller import MapController
    from app.qtui.utils import run_on_ui

    view._region_map._map_controller = MapController(
        MapMarkerService(root=marker_root),
        task_scope=view._region_map._marker_scope,
        post_to_ui=lambda callback: run_on_ui(callback),
        get_generation=lambda: view._region_map._host_generation,
    )

    view.on_save_selected(str(world))
    assert _wait_until(lambda: view.world_session is not None)
    assert _wait_until(
        lambda: view._region_map.map_controller.world_path is not None
    )

    coordinator = view._region_map
    coordinator._add_marker("Camp", 64, -32)
    assert _wait_until(lambda: len(coordinator.map_controller.markers()) == 1)
    markers = coordinator.map_controller.markers()
    assert markers[0].name == "Camp"
    assert panel_has_marker(coordinator.panel, "Camp")

    coordinator._on_search("Camp")
    assert coordinator.panel.selected_marker_id == markers[0].id

    coordinator.panel._selected_marker_id = markers[0].id
    coordinator._delete_selected_marker()
    assert _wait_until(lambda: len(coordinator.map_controller.markers()) == 0)


def panel_has_marker(panel: object, name: str) -> bool:
    list_widget = getattr(panel, "_marker_list")
    for row in range(list_widget.count()):
        item = list_widget.item(row)
        if item is not None and name in item.text():
            return True
    return False


def test_region_map_delete_selected_region(
    view: ExplorerView,
    host: FakeHost,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    region_dir = tmp_path / "region"
    region_dir.mkdir(parents=True, exist_ok=True)
    keep = region_dir / "r.1.0.mca"
    target = region_dir / "r.0.0.mca"
    keep.write_bytes(b"1" * 2048)
    target.write_bytes(b"0" * 4096)

    view.on_save_selected(str(tmp_path))
    assert _wait_until(lambda: view.world_session is not None)
    coordinator = view._region_map
    panel = coordinator.panel
    assert _wait_until(lambda: len(panel.canvas._regions) == 2)

    panel.canvas.select_region((0, 0))
    assert coordinator.selected_region == (0, 0)
    monkeypatch.setattr(panel, "confirm_delete_region", lambda _coord: True)

    coordinator._delete_selected_region()
    assert _wait_until(lambda: not target.exists())
    assert keep.exists()
    assert _wait_until(lambda: any(
        "r.0.0.mca" in message for _title, message in host.infos
    ))
    assert host.transactions.calls
    assert host.transactions.calls[0][1] == "删除区域前自动备份"
    assert _wait_until(lambda: len(panel.canvas._regions) == 1)
    assert (1, 0) in panel.canvas._regions
    assert coordinator.selected_region is None
    assert panel._delete_region.isEnabled() is False


def test_chunk_nbt_load_and_stage_from_map_selection(
    view: ExplorerView,
    tmp_path: Path,
) -> None:
    from core.mca import WritableRegion
    import core.nbt as nbtlib

    region_dir = tmp_path / "region"
    region_dir.mkdir(parents=True, exist_ok=True)
    path = region_dir / "r.0.0.mca"
    writer = WritableRegion.empty(path)
    writer.set_chunk(0, 0, nbtlib.File({
        "DataVersion": nbtlib.Int(3463),
        "xPos": nbtlib.Int(0),
        "zPos": nbtlib.Int(0),
        "Status": nbtlib.String("full"),
    }))
    writer.save(path, backup=False)

    view.on_save_selected(str(tmp_path))
    assert _wait_until(lambda: view.world_session is not None)

    view._open_region_nbt(0, 0, "overworld")
    coordinator = view._nbt_coordinator
    panel = coordinator.panel

    assert _wait_until(lambda: coordinator.chunk_target is not None)
    assert view._tabs.currentIndex() == 5
    assert panel.region_file_text == "region/r.0.0.mca"
    assert panel._status.text().startswith("已加载:")
    assert coordinator.chunk_target is not None
    assert coordinator.chunk_target.chunk_x == 0

    tree = panel._tree
    assert tree.topLevelItemCount() > 0
    status_item = None
    for index in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(index)
        if item is not None and item.text(0) == "Status":
            status_item = item
            break
    assert status_item is not None
    assert tree.stage_item_value(status_item, "edited")
    assert len(coordinator.staged_changes) == 1
    change = coordinator.staged_changes[0]
    assert change.format == "chunk"
    assert change.display_path.endswith("Status")


def test_player_form_stage_goes_to_shared_nbt_store(
    view: ExplorerView,
    host: FakeHost,
    tmp_path: Path,
) -> None:
    view.on_save_selected(str(tmp_path))
    assert _wait_until(lambda: view._players.editor.player_data is not None)

    editor = view._players.editor
    editor._fields["Health"].setText("20")
    view._stage_player_form()

    assert len(view._nbt_coordinator.staged_changes) >= 1
    change = view._nbt_coordinator.staged_changes[0]
    assert change.path == ("Health",)
    assert view._tabs.currentIndex() == 5
    assert any("已暂存" in title for title, _message in host.infos)


def test_player_export_writes_summary_file(
    view: ExplorerView,
    host: FakeHost,
    tmp_path: Path,
) -> None:
    view.on_save_selected(str(tmp_path))
    assert _wait_until(lambda: view._players.editor.player_data is not None)

    output = tmp_path / "alex.json"
    host.save_path = str(output)
    view._export_player_summary()

    assert _wait_until(lambda: output.exists())
    payload = output.read_text(encoding="utf-8")
    assert "Alex" in payload
    assert any("导出成功" in title for title, _message in host.infos)


def test_nbt_document_load_and_leaf_edit_are_staged(
    view: ExplorerView,
    tmp_path: Path,
) -> None:
    view.on_save_selected(str(tmp_path))
    coordinator = view._nbt_coordinator
    panel = coordinator.panel

    assert _wait_until(lambda: panel._tree.topLevelItemCount() > 0)
    data_item = panel._tree.topLevelItem(0)
    assert data_item is not None
    data_item.setExpanded(True)
    assert _wait_until(lambda: data_item.childCount() == 2)
    level_name = data_item.child(1)
    if level_name is not None and level_name.text(0) != "LevelName":
        level_name = data_item.child(0)
    assert level_name is not None
    assert level_name.text(0) == "LevelName"

    assert panel._tree.stage_item_value(level_name, "Renamed World")
    assert len(coordinator.staged_changes) == 1
    change = coordinator.staged_changes[0]
    assert change.path == ("Data", "LevelName")
    assert isinstance(change.new_value, String)
    assert str(change.new_value) == "Renamed World"
    assert panel._stages.rowCount() == 1


def test_nbt_commit_success_clears_snapshot_and_reloads_world(
    view: ExplorerView,
    host: FakeHost,
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    view.on_save_selected(str(tmp_path))
    coordinator = view._nbt_coordinator
    panel = coordinator.panel
    assert _wait_until(lambda: panel._tree.topLevelItemCount() > 0)
    coordinator.stage_change(
        ("Data", "GameType"),
        Int(0),
        Int(1),
        "Data.GameType",
    )
    monkeypatch.setattr(panel, "confirm_commit", lambda _changes: True)
    monkeypatch.setattr(
        "app.qtui.views.nbt_tasks.commit_nbt_changes",
        lambda session, changes, token: NbtCommitResult(
            session.world_path,
            len(changes),
            len(changes),
            True,
        ),
    )

    coordinator.commit_all()

    assert _wait_until(lambda: len(host.repository.opened) == 2)
    assert coordinator.staged_changes == ()
    assert any(title == "提交完成" for title, _message in host.infos)


def test_nbt_commit_failure_keeps_staged_snapshot(
    view: ExplorerView,
    host: FakeHost,
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    view.on_save_selected(str(tmp_path))
    coordinator = view._nbt_coordinator
    assert _wait_until(
        lambda: coordinator.panel._tree.topLevelItemCount() > 0
    )
    coordinator.stage_change(
        ("Data", "GameType"), Int(0), Int(1), "Data.GameType"
    )
    monkeypatch.setattr(
        coordinator.panel, "confirm_commit", lambda _changes: True
    )

    def fail_commit(
        _session: object,
        _changes: object,
        _token: object,
    ) -> NbtCommitResult:
        raise OSError("backup failed")

    monkeypatch.setattr(
        "app.qtui.views.nbt_tasks.commit_nbt_changes",
        fail_commit,
    )

    coordinator.commit_all()

    assert _wait_until(lambda: bool(host.errors))
    assert len(coordinator.staged_changes) == 1
    assert host.errors[-1][0] == "提交失败"


def test_clear_world_rejects_stale_player_detail(
    view: ExplorerView,
    tmp_path: Path,
) -> None:
    view.on_save_selected(str(tmp_path))
    assert _wait_until(lambda: view._players.current_uuid is not None)
    session = cast(_Session, view.world_session)
    service = PlayerService()
    summary = service.load_summary(cast(Any, session), session.player_uuid)
    assert summary is not None
    detail = PlayerDetailResult(
        player_data=session.player_data,
        summary=summary,
        containers=service.load_containers(
            cast(Any, session), session.player_uuid
        ),
        attributes=(),
        effects=(),
    )
    world_generation = view._player_tasks._world_generation
    detail_generation = view._player_tasks._detail_generation

    view.on_save_cleared()
    view._apply_player_detail(
        detail,
        session.player_uuid,
        world_generation,
        detail_generation,
    )

    assert view._players.current_uuid is None
    assert "Alex" not in view._players.editor.summary_text()


def test_stats_analysis_reuses_index_and_projects_tables(
    view: ExplorerView,
    host: FakeHost,
    tmp_path: Path,
) -> None:
    view.on_save_selected(str(tmp_path))
    assert _wait_until(lambda: view.world_session is not None)

    view._stats_coordinator.start()

    panel = view._stats_coordinator.panel
    assert _wait_until(lambda: panel.view_state is not None)
    assert host.stats_service.calls == [tmp_path.resolve()]
    assert host.repository.index_requests == [tmp_path.resolve()]
    assert panel.view_state is not None
    assert panel.view_state.total_blocks == 120
    assert panel._summary.rowCount() == 9
    assert panel._dimensions.rowCount() == 1
    assert panel._players.rowCount() == 1
    assert panel._rankings.rowCount() >= 3
    assert panel._progress.value() == 100

    panel._sort.setCurrentIndex(panel._sort.findData("deaths"))
    metric_item = panel._players.item(0, 1)
    assert metric_item is not None
    assert metric_item.text() == "2"


def test_stats_world_clear_cancels_and_rejects_result(
    view: ExplorerView,
    host: FakeHost,
    tmp_path: Path,
) -> None:
    host.stats_service.should_block = True
    view.on_save_selected(str(tmp_path))
    assert _wait_until(lambda: view.world_session is not None)
    view._stats_coordinator.start()
    assert host.stats_service.started.wait(1.0)

    view.on_save_cleared()
    host.stats_service.release.set()
    panel = view._stats_coordinator.panel

    assert host.stats_service.completed.wait(1.0)
    assert _wait_until(
        lambda: view._stats_coordinator._tasks._scope.active_task_count == 0
    )
    assert panel.view_state is None
    assert panel._summary.rowCount() == 0
    assert panel._start.isEnabled() is False


def test_search_projects_results_and_exports_full_snapshot(
    view: ExplorerView,
    host: FakeHost,
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    view.on_save_selected(str(tmp_path))
    assert _wait_until(lambda: view.world_session is not None)
    service = view._search_coordinator._service
    monkeypatch.setattr(
        service,
        "search_condition",
        lambda condition: [SearchResult(
            condition.search_type,
            condition.target,
            (3, 70, 4),
            condition.dimensions[0],
            {"id": condition.target},
        )],
    )
    panel = view._search_coordinator.panel
    panel._target.setText("minecraft:zombie")
    view._search_coordinator.start_search()

    assert _wait_until(lambda: len(panel.results) == 1)
    assert panel._table.rowCount() == 1
    target_item = panel._table.item(0, 1)
    assert target_item is not None
    assert target_item.text() == "minecraft:zombie"

    output = tmp_path / "search-results.txt"
    host.save_path = str(output)
    view._search_coordinator.export_results()

    assert _wait_until(lambda: bool(host.infos))
    assert output.is_file()
    assert "minecraft:zombie" in output.read_text(encoding="utf-8")
    assert host.infos[0][0] == "导出成功"


def test_search_world_clear_cancels_and_drops_result(
    view: ExplorerView,
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    view.on_save_selected(str(tmp_path))
    assert _wait_until(lambda: view.world_session is not None)
    started = Event()
    release = Event()

    def blocked_search(condition: object) -> list[SearchResult]:
        del condition
        started.set()
        release.wait(2.0)
        return [SearchResult("entity", "old", (1, 64, 1), "overworld")]

    monkeypatch.setattr(
        view._search_coordinator._service,
        "search_condition",
        blocked_search,
    )
    panel = view._search_coordinator.panel
    panel._target.setText("old")
    view._search_coordinator.start_search()
    assert started.wait(1.0)

    view.on_save_cleared()
    release.set()

    assert _wait_until(
        lambda: view._search_coordinator._scope.active_task_count == 0
    )
    assert panel.results == ()
    assert panel._table.rowCount() == 0
    assert panel._search.isEnabled() is False


def test_did_mount_loads_existing_current_save(
    view: ExplorerView,
    host: FakeHost,
    tmp_path: Path,
) -> None:
    host.current_path = str(tmp_path)

    view.did_mount()

    assert _wait_until(lambda: view.world_session is not None)
    assert host.repository.opened == [tmp_path.resolve()]


def test_invalid_world_restores_retryable_empty_state(
    view: ExplorerView,
    host: FakeHost,
    tmp_path: Path,
) -> None:
    host.repository.error = FileNotFoundError("missing level.dat")

    view.on_save_selected(str(tmp_path))

    assert _wait_until(lambda: bool(host.errors))
    assert host.errors[0][0] == "无效的存档"
    assert view._loaded_world_path is None
    assert view.world_session is None


def test_clear_world_rejects_stale_result(
    view: ExplorerView,
    tmp_path: Path,
) -> None:
    generation = view._tasks.load_generation
    stale_session = cast(Any, _Session(tmp_path))
    stale = ExplorerWorldSnapshot(
        stale_session,
        stale_session.get_world_info(),
        {},
    )

    view.on_save_cleared()
    view._apply_loaded_world(stale, generation)

    assert view.world_session is None
    assert view._loaded_world_path is None


def test_quick_backup_uses_service_and_restores_button(
    view: ExplorerView,
    host: FakeHost,
    tmp_path: Path,
) -> None:
    view.on_save_selected(str(tmp_path))
    assert _wait_until(lambda: view.world_session is not None)

    view._create_backup()

    assert _wait_until(lambda: bool(host.infos))
    assert host.backup_service.calls == [tmp_path.resolve()]
    assert "backup" in host.infos[0][1]
    assert view._tasks.is_backup_running is False


def test_backup_without_world_warns_and_restore_switches_view(
    view: ExplorerView,
    host: FakeHost,
) -> None:
    view._create_backup()
    view._open_backup_center()

    assert host.warns == [("提示", "请先加载存档")]
    assert host.views.switched == ["backup_center"]


@pytest.mark.parametrize(
    ("phase", "completed", "total", "expected"),
    [
        (WorldIndexBuildPhase.VALIDATING, 0, None, 20.0),
        (WorldIndexBuildPhase.PROBING, 1, 2, 76.0),
        (WorldIndexBuildPhase.FINALIZING, 2, 2, 92.0),
        (WorldIndexBuildPhase.COMPLETE, 2, 2, 95.0),
    ],
)
def test_index_progress_mapping_is_bounded(
    tmp_path: Path,
    phase: WorldIndexBuildPhase,
    completed: int,
    total: int | None,
    expected: float,
) -> None:
    frame = WorldIndexProgressFrame(
        tmp_path,
        phase,
        completed,
        total,
        discovered_files=0,
        stamped_files=completed,
    )

    value, _stage = map_index_progress(frame)

    assert value == expected
