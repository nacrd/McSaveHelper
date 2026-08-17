"""Qt 迁移视图的表单、后台任务与生命周期测试。"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Iterator, Optional, cast

import pytest
from PySide6.QtWidgets import QApplication

from app.models.config import MigrationConfig
from app.qtui.context import QtMigrationCommands
from app.qtui.views.migrator import (
    MigratorHost,
    MigratorView,
)
from app.qtui.views.migrator_tasks import BatchScanResult, UuidQueryResult
from app.services.execution_runtime import ExecutionRuntime, LaneLimits


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


class _MigrationService:
    """迁移视图测试所需的只读服务边界。"""

    def __init__(self) -> None:
        self.batch_worlds: list[Path] = []
        self.scan_result = ""
        self.scanned_paths: list[str] = []

    def scan_batch_dir(self, directory: str) -> list[Path]:
        self.scanned_paths.append(directory)
        self.batch_worlds = [Path(directory) / "world-a"]
        self.scan_result = "找到 1 个世界存档"
        return self.batch_worlds


class _UuidService:
    """返回确定 UUID 的测试服务。"""

    @staticmethod
    def generate_offline_uuid(name: str) -> str:
        return f"offline-{name}"

    @staticmethod
    def query_online_uuid(
        name: str,
        log: Callable[[str, str], None],
    ) -> tuple[str, str]:
        del log
        return f"online-{name}", name


class _Config:
    """迁移视图需要的最小配置端口。"""

    def __init__(self) -> None:
        self.migration = MigrationConfig()


class FakeHost:
    """实现 MigratorHost 的隔离测试宿主。"""

    def __init__(self) -> None:
        limits = LaneLimits(max_workers=2, queue_capacity=8)
        self.runtime = ExecutionRuntime(io_limits=limits, cpu_limits=limits)
        self.config = _Config()
        self.migration = _MigrationService()
        self.uuid = _UuidService()
        self.logs: list[tuple[str, str]] = []
        self.warns: list[tuple[str, str]] = []
        self.errors: list[tuple[str, str]] = []
        self.statuses: list[tuple[str, int]] = []
        self.starts = 0
        self.cancels = 0
        self.cancel_result = False
        self.destination_picks = 0
        self.batch_picks = 0
        self.migration_commands = QtMigrationCommands(
            start=self._start,
            cancel=self._cancel,
            choose_destination=self._choose_destination,
            choose_batch_directory=self._choose_batch,
        )

    def translate(self, key: str, default: str = "", **kwargs: Any) -> str:
        del key
        return default.format(**kwargs)

    def log(self, msg: str, level: str = "INFO") -> None:
        self.logs.append((msg, level))

    def warn_dialog(self, title: str, message: str) -> None:
        self.warns.append((title, message))

    def info_dialog(self, title: str, message: str) -> None:
        del title, message

    def show_status_message(self, message: str, timeout_ms: int = 5000) -> None:
        self.statuses.append((message, timeout_ms))

    def error_dialog(
        self,
        title: str,
        message: str,
        exception: Optional[Exception] = None,
        show_details: bool = False,
    ) -> None:
        del exception, show_details
        self.errors.append((title, message))

    def handle_exception(
        self,
        exception: Exception,
        title: Optional[str] = None,
        log: bool = True,
        show_dialog: bool = True,
    ) -> None:
        del log, show_dialog
        self.errors.append((title or "异常", str(exception)))

    @property
    def execution_runtime(self) -> ExecutionRuntime:
        return self.runtime

    def _start(self) -> None:
        self.starts += 1

    def _cancel(self) -> bool:
        self.cancels += 1
        return self.cancel_result

    def _choose_destination(self) -> None:
        self.destination_picks += 1

    def _choose_batch(self) -> None:
        self.batch_picks += 1

    def close(self) -> None:
        self.runtime.shutdown(wait=True, timeout=5.0)


@pytest.fixture
def host(qt_app: object) -> Iterator[FakeHost]:
    del qt_app
    fake = FakeHost()
    yield fake
    fake.close()


@pytest.fixture
def view(host: FakeHost) -> Iterator[MigratorView]:
    migrator = MigratorView(cast(MigratorHost, host))
    yield migrator
    migrator.dispose()


def test_form_changes_sync_to_migration_config(
    view: MigratorView,
    host: FakeHost,
) -> None:
    view._directory.destination.setText("D:/exports")
    view._directory.world_name.setText("converted")
    view._player.manual_names.setText("Steve, Alex")
    view._options.offline.setChecked(True)
    view._mode.full.setChecked(True)

    config = host.config.migration
    assert config.dest_path == "D:/exports"
    assert config.world_name == "converted"
    assert config.manual_names == "Steve, Alex"
    assert config.offline_mode is True
    assert config.mode == "full"


def test_top_actions_start_and_cancel_commands(
    view: MigratorView,
    host: FakeHost,
) -> None:
    start, cancel = view.get_top_actions()

    assert start.enabled is True
    assert cancel.enabled is False

    start.handler()
    cancel.handler()

    assert host.starts == 1
    assert host.cancels == 1
    assert host.warns == [("提示", "当前没有运行中的迁移任务")]

    view.set_start_enabled(False)
    start, cancel = view.get_top_actions()
    assert start.enabled is False
    assert cancel.enabled is True


def test_public_path_updates_sync_config(
    view: MigratorView,
    host: FakeHost,
) -> None:
    view.set_path_value("source", "D:/world")
    view.set_path_value("destination", "D:/output")
    view.set_path_value("batch", "D:/worlds")

    config = host.config.migration
    assert config.src_path == "D:/world"
    assert config.dest_path == "D:/output"
    assert config.batch_dir_path == "D:/worlds"
    with pytest.raises(ValueError, match="未知路径目标"):
        view.set_path_value("missing", "")


def test_batch_scan_uses_runtime_and_updates_result(
    view: MigratorView,
    host: FakeHost,
    tmp_path: Path,
) -> None:
    view.set_path_value("batch", str(tmp_path))

    view._scan_batch()

    assert _wait_until(lambda: view._batch.scan_button.isEnabled())
    assert host.migration.scanned_paths == [str(tmp_path)]
    assert view._batch.result.text() == "找到 1 个世界存档"
    assert host.logs[-1] == ("批量扫描完成: 找到 1 个世界存档", "SUCCESS")


def test_uuid_query_uses_runtime_and_formats_result(
    view: MigratorView,
) -> None:
    view._player.query_name.setText("Steve")

    view._query_uuid()

    assert _wait_until(lambda: view._player.query_button.isEnabled())
    result = view._player.query_result.text()
    assert "离线 UUID: offline-Steve" in result
    assert "正版 UUID: online-Steve" in result


def test_stale_and_disposed_results_are_ignored(
    view: MigratorView,
) -> None:
    view._player.query_name.setText("Alex")
    view._tasks.invalidate_query()
    view._tasks.invalidate_query()
    generation = view._tasks.query_generation
    original = view._player.query_result.text()
    result = UuidQueryResult("offline", "online", "Alex")

    view._apply_uuid_query_success(result, "Alex", generation - 1)
    view.dispose()
    view._apply_uuid_query_success(result, "Alex", generation)

    assert view._player.query_result.text() == original


def test_stale_batch_result_is_ignored(view: MigratorView) -> None:
    view.set_path_value("batch", "D:/new")
    view._tasks.scan("D:/old")
    generation = view._tasks.scan_generation
    original = view._batch.result.text()

    view._apply_batch_scan_success(
        BatchScanResult((Path("D:/old/world"),), "stale"),
        "D:/old",
        generation,
    )

    assert view._batch.result.text() == original


def test_save_selection_updates_source_and_dispose_is_idempotent(
    view: MigratorView,
    host: FakeHost,
) -> None:
    view.on_save_selected("D:/selected-world")
    assert host.config.migration.src_path == "D:/selected-world"

    view.on_save_cleared()
    view.dispose()
    view.dispose()

    assert host.config.migration.src_path == ""
    assert view._disposed is True
