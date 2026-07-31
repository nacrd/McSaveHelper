"""Qt 备份中心视图测试：刷新、空状态、校验与生命周期。"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

import pytest
from PySide6.QtWidgets import QApplication

from app.adapters.file_dialogs import FileType
from app.qtui.views.backup_center import BackupCenterView
from app.services.backup_service import BackupService
from app.services.execution_runtime import ExecutionRuntime, LaneLimits
from app.services.world_write_coordinator import WorldWriteCoordinator


def _wait_until(
    predicate: Callable[[], bool],
    timeout_s: float = 5.0,
) -> bool:
    """轮询等待条件成立（避免固定长 sleep 协调）。"""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app = QApplication.instance()
        if app is not None:
            app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


class FakeHost:
    """实现 BackupHost 端口的最小测试宿主。"""

    def __init__(self, service: BackupService) -> None:
        limits = LaneLimits(max_workers=2, queue_capacity=8)
        self.runtime = ExecutionRuntime(io_limits=limits, cpu_limits=limits)
        self.service = service
        self.infos: list[tuple[str, str]] = []
        self.warns: list[tuple[str, str]] = []
        self.errors: list[tuple[str, str]] = []

    def translate(self, key: str, default: str = "", **kwargs: Any) -> str:
        del kwargs
        return default

    def log(self, msg: str, level: str = "INFO") -> None:
        del msg, level

    def info_dialog(self, title: str, message: str) -> None:
        self.infos.append((title, message))

    def warn_dialog(self, title: str, message: str) -> None:
        self.warns.append((title, message))

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

    def pick_directory(self) -> Optional[str]:
        return None

    def pick_file(
        self,
        title: str = "",
        file_types: Optional[list[FileType]] = None,
    ) -> Optional[str]:
        del title, file_types
        return None

    def pick_files(
        self,
        title: str = "",
        file_types: Optional[list[FileType]] = None,
    ) -> Optional[list[str]]:
        del title, file_types
        return None

    def save_file(
        self,
        title: str = "",
        default_ext: str = ".txt",
        file_types: Optional[list[FileType]] = None,
    ) -> Optional[str]:
        del title, default_ext, file_types
        return None

    def show_progress(self, task_name: str = "") -> None:
        del task_name

    def hide_progress(self) -> None:
        return None

    def update_progress_with_task(self, task_name: str, value: float) -> None:
        del task_name, value

    @property
    def execution_runtime(self) -> ExecutionRuntime:
        return self.runtime

    @property
    def backup(self) -> BackupService:
        return self.service

    def close(self) -> None:
        self.runtime.shutdown(wait=True, timeout=5.0)


def _make_world(tmp_path: Path) -> Path:
    world = tmp_path / "world"
    world.mkdir()
    (world / "level.dat").write_bytes(b"level")
    return world


@pytest.fixture
def host(qt_app: object, tmp_path: Path) -> Iterator[FakeHost]:
    del qt_app, tmp_path
    service = BackupService(WorldWriteCoordinator())
    fake = FakeHost(service)
    yield fake
    fake.close()


@pytest.fixture
def view(host: FakeHost) -> Iterator[BackupCenterView]:
    yield BackupCenterView(host)


def _widget_count(view: BackupCenterView) -> int:
    """统计备份列表中的实际控件数量（不含拉伸项）。"""
    count = 0
    for index in range(view._backup_list_layout.count()):
        item = view._backup_list_layout.itemAt(index)
        if item is not None and item.widget() is not None:
            count += 1
    return count


def test_backup_center_keeps_creation_next_to_form(view: BackupCenterView) -> None:
    assert view.get_top_actions() == []


def test_backup_center_shows_empty_state_without_save(view: BackupCenterView) -> None:
    view._refresh()

    assert view._summary.text() == "尚未选择存档"
    assert _widget_count(view) == 1


def test_backup_center_tracks_selected_world_and_renders_records(
    view: BackupCenterView,
    host: FakeHost,
    tmp_path: Path,
) -> None:
    world = _make_world(tmp_path)
    host.service.create_backup(world, "测试恢复点")

    view.on_save_selected(str(world))

    assert _wait_until(lambda: view._summary.text() == "共 1 个恢复点")
    assert view._world_path_field.text() == str(world)
    assert _widget_count(view) == 1


def test_backup_center_refresh_failure_shows_placeholder(
    view: BackupCenterView,
    host: FakeHost,
    tmp_path: Path,
) -> None:
    world = tmp_path / "not-a-world"
    view._world_path_field.setText(str(world))

    view._refresh()

    assert _wait_until(lambda: "加载失败" in view._summary.text())
    assert _widget_count(view) == 1


def test_backup_center_warns_without_world(view: BackupCenterView, host: FakeHost) -> None:
    view._start_create()

    assert host.warns == [("提示", "请先选择有效存档")]
    assert not view._busy


def test_backup_center_busy_state_disables_actions(
    view: BackupCenterView,
) -> None:
    view._set_busy(True)

    assert not view._create_button.isEnabled()
    assert not view._retention_dropdown.isEnabled()
    assert not view._cancel_button.isHidden()

    view._set_busy(False)
    assert view._create_button.isEnabled()
    assert view._cancel_button.isHidden()


def test_backup_center_dispose_is_idempotent(view: BackupCenterView) -> None:
    view.dispose()
    view.dispose()

    assert view._refresh_generation >= 1
