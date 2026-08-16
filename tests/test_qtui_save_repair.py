"""Qt 存档修复视图测试：构建、检测流程、存档选择与生命周期。"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

import pytest
from PySide6.QtWidgets import QApplication

from app.adapters.file_dialogs import FileType
from app.controllers.save_repair_controller import RepairOptions
from app.qtui.views.save_repair import SaveRepairView
from app.services.execution_runtime import ExecutionRuntime, LaneLimits
from app.services.save_repair.models import DetectReport, WorldInfo
from app.services.save_repair_service import SaveRepairService


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


class FakeSaveRepairService:
    """最小修复服务：记录参数并返回预设报告。"""

    def __init__(self) -> None:
        self.detect_report = DetectReport(
            world_info=WorldInfo(
                world_name="TestWorld",
                version_name="1.20.4",
                data_version=3700,
                difficulty_name="normal",
                seed=12345,
                world_size_mb=1.5,
                total_files=10,
                region_count=2,
                total_chunks=16,
                player_count=1,
            ),
            chunks_checked=16,
            chunks_damaged=0,
        )
        self.detect_calls: list[str] = []
        self.repair_calls: list[tuple[str, RepairOptions]] = []
        self.cancel_calls = 0

    def detect_world(
        self,
        world_path: Path,
        progress_callback: Any = None,
        log_callback: Any = None,
    ) -> DetectReport:
        del progress_callback, log_callback
        self.detect_calls.append(str(world_path))
        return self.detect_report

    def repair_world(
        self,
        *,
        world_path: Path,
        fix_chunks: bool,
        fix_players: bool,
        fix_level_dat: bool,
        backup: bool,
        progress_callback: Any = None,
        log_callback: Any = None,
    ) -> Any:
        del progress_callback, log_callback
        self.repair_calls.append(
            (
                str(world_path),
                RepairOptions(fix_chunks, fix_players, fix_level_dat, backup),
            )
        )
        return None

    def cancel(self) -> None:
        self.cancel_calls += 1


class FakeHost:
    """实现 SaveRepairHost 端口的最小测试宿主。"""

    def __init__(self) -> None:
        limits = LaneLimits(max_workers=2, queue_capacity=8)
        self.runtime = ExecutionRuntime(io_limits=limits, cpu_limits=limits)
        self.service = FakeSaveRepairService()
        self.infos: list[tuple[str, str]] = []
        self.warns: list[tuple[str, str]] = []
        self.errors: list[tuple[str, str]] = []
        self.progress_shown: list[str] = []
        self.progress_updates: list[tuple[str, float]] = []
        self.progress_hidden = 0

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
        self.progress_shown.append(task_name)

    def hide_progress(self) -> None:
        self.progress_hidden += 1

    def update_progress_with_task(self, task_name: str, value: float) -> None:
        self.progress_updates.append((task_name, value))

    @property
    def execution_runtime(self) -> ExecutionRuntime:
        return self.runtime

    @property
    def save_repair(self) -> SaveRepairService:
        return self.service  # type: ignore[return-value]

    def close(self) -> None:
        self.runtime.shutdown(wait=True, timeout=5.0)


@pytest.fixture
def host(qt_app: object) -> Iterator[FakeHost]:
    del qt_app
    fake = FakeHost()
    yield fake
    fake.close()


@pytest.fixture
def view(host: FakeHost) -> Iterator[SaveRepairView]:
    yield SaveRepairView(host)


def test_view_builds_form(view: SaveRepairView) -> None:
    assert view._fix_chunks_checkbox.isChecked() is True
    assert view._fix_players_checkbox.isChecked() is True
    assert view._fix_level_dat_checkbox.isChecked() is True
    assert view._backup_checkbox.isChecked() is True
    assert view.get_top_actions() == []
    # 取消按钮初始隐藏
    assert view._cancel_button.isHidden()


def test_view_detect_warns_without_path(
    view: SaveRepairView,
    host: FakeHost,
) -> None:
    view._start_detect()

    assert host.warns == [("提示", "请先通过侧边栏设置当前存档目录")]
    assert not view._busy
    assert view._detect_button.isEnabled()


def test_view_detect_publishes_report(
    view: SaveRepairView,
    host: FakeHost,
    tmp_path: Path,
) -> None:
    view._world_path_field.setText(str(tmp_path))

    view._start_detect()

    assert _wait_until(lambda: not view._busy)
    assert host.service.detect_calls == [str(tmp_path)]
    assert not view._world_info_card.isHidden()
    assert not view._detect_result_card.isHidden()
    assert "TestWorld" in view._world_info_text.text()
    assert "区块" in view._detect_result_text.text()


def test_view_repair_passes_options(
    view: SaveRepairView,
    host: FakeHost,
    tmp_path: Path,
) -> None:
    view._world_path_field.setText(str(tmp_path))
    view._fix_chunks_checkbox.setChecked(False)
    view._fix_players_checkbox.setChecked(False)
    view._fix_level_dat_checkbox.setChecked(False)
    view._backup_checkbox.setChecked(False)

    view._start_repair()

    assert _wait_until(lambda: not view._busy)
    assert len(host.service.repair_calls) == 1
    _path, options = host.service.repair_calls[0]
    assert _path == str(tmp_path)
    assert options == RepairOptions(False, False, False, False)


def test_view_busy_state_disables_actions(
    view: SaveRepairView,
    host: FakeHost,
    tmp_path: Path,
) -> None:
    del host
    view._world_path_field.setText(str(tmp_path))

    view._set_busy(True)

    assert not view._detect_button.isEnabled()
    assert not view._repair_button.isEnabled()
    assert not view._cancel_button.isHidden()

    view._set_busy(False)
    assert view._detect_button.isEnabled()
    assert view._cancel_button.isHidden()


def test_view_save_selected_updates_path_and_hides_results(
    view: SaveRepairView,
    tmp_path: Path,
) -> None:
    view._world_info_card.setVisible(True)
    view._detect_result_card.setVisible(True)

    view.on_save_selected(str(tmp_path))

    assert view._world_path_field.text() == str(tmp_path)
    assert view._world_info_card.isHidden()
    assert view._detect_result_card.isHidden()


def test_view_save_cleared_resets_state(view: SaveRepairView) -> None:
    view._world_info_card.setVisible(True)
    view._detect_result_card.setVisible(True)
    view._result_text.setText("旧结果")

    view.on_save_cleared()

    assert view._world_path_field.text() == ""
    assert view._world_info_card.isHidden()
    assert view._detect_result_card.isHidden()
    assert view._result_text.text() == ""


def test_view_dispose_closes_controller(view: SaveRepairView) -> None:
    view.dispose()

    # 关闭后再次提交任务应被拒绝（控制器已关闭）
    view._start_detect()
    assert not view._busy


def test_view_append_log_colors_levels(view: SaveRepairView) -> None:
    view._append_log("开始", "INFO")
    view._append_log("警告", "WARNING")
    view._append_log("错误", "ERROR")

    html = view._log_view.toHtml()
    assert "开始" in html
    assert "警告" in html
    assert "错误" in html
