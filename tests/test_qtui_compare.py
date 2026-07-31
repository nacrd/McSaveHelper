"""Qt 存档对比视图测试：校验、对比流程、存档选择与生命周期。"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

import pytest
from PySide6.QtWidgets import QApplication

from app.adapters.file_dialogs import FileType
from app.qtui.views.compare import CompareView
from app.services.execution_runtime import ExecutionRuntime, LaneLimits
from app.services.world_compare_service import (
    CompareItem,
    WorldCompareResult,
    WorldCompareService,
)


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


class FakeWorldCompareService:
    """最小对比服务：记录路径并返回预设结果。"""

    def __init__(self) -> None:
        self.result = WorldCompareResult(
            summary={"changed": 1, "total": 3},
            world_info=[CompareItem(name="level-name", left="A", right="B", same=False)],
            players=[],
            regions=[],
        )
        self.calls: list[tuple[str, str]] = []

    def compare_worlds(self, left: Path, right: Path) -> WorldCompareResult:
        self.calls.append((str(left), str(right)))
        return self.result


class FakeHost:
    """实现 CompareHost 端口的最小测试宿主。"""

    def __init__(self) -> None:
        limits = LaneLimits(max_workers=2, queue_capacity=8)
        self.runtime = ExecutionRuntime(io_limits=limits, cpu_limits=limits)
        self.service = FakeWorldCompareService()
        self.warns: list[tuple[str, str]] = []
        self.errors: list[tuple[str, str]] = []
        self.picked: Optional[str] = None

    def translate(self, key: str, default: str = "", **kwargs: Any) -> str:
        del kwargs
        return default

    def log(self, msg: str, level: str = "INFO") -> None:
        del msg, level

    def info_dialog(self, title: str, message: str) -> None:
        del title, message

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
        return self.picked

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
    def world_compare(self) -> WorldCompareService:
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
def view(host: FakeHost) -> Iterator[CompareView]:
    yield CompareView(host)


def _make_world(tmp_path: Path, name: str) -> Path:
    world = tmp_path / name
    world.mkdir()
    (world / "level.dat").write_bytes(b"placeholder")
    return world


def test_view_builds_and_top_action(view: CompareView) -> None:
    actions = view.get_top_actions()
    assert [action.label for action in actions] == ["开始对比"]


def test_compare_warns_without_baseline(view: CompareView, host: FakeHost) -> None:
    view._compare()

    assert host.warns[0][1] == "请先通过侧边栏设置有效基准存档目录。"
    assert not view._state.is_comparing


def test_compare_warns_without_target(
    view: CompareView,
    host: FakeHost,
    tmp_path: Path,
) -> None:
    left = _make_world(tmp_path, "left")
    view._left_field.setText(str(left))

    view._compare()

    assert host.warns[-1][1] == "请指定包含 level.dat 的有效目标存档目录。"


def test_compare_publishes_result(
    view: CompareView,
    host: FakeHost,
    tmp_path: Path,
) -> None:
    left = _make_world(tmp_path, "left")
    right = _make_world(tmp_path, "right")
    view._left_field.setText(str(left))
    view._right_field.setText(str(right))

    view._compare()

    assert _wait_until(lambda: not view._state.is_comparing)
    assert host.service.calls == [(str(left), str(right))]
    assert "level-name" in view._summary.text() or view._result_layout.count() > 0
    assert any(group.items for group in view._state.groups)


def test_compare_rejects_missing_level_dat(
    view: CompareView,
    host: FakeHost,
    tmp_path: Path,
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    left = _make_world(tmp_path, "left")
    view._left_field.setText(str(left))
    view._right_field.setText(str(empty))

    view._compare()

    assert _wait_until(lambda: not view._state.is_comparing)
    assert host.errors != []


def test_pick_target_updates_field(view: CompareView, host: FakeHost, tmp_path: Path) -> None:
    host.picked = str(tmp_path)

    view._pick_target()

    assert view._right_field.text() == str(tmp_path)


def test_save_selected_sets_baseline(view: CompareView, tmp_path: Path) -> None:
    path = _make_world(tmp_path, "left")

    view.on_save_selected(str(path))

    assert view._left_field.text() == str(path)
    assert view._state.left_path == path


def test_save_cleared_resets_baseline(view: CompareView) -> None:
    view.on_save_selected(str(Path("/tmp/example")))
    view.on_save_cleared()

    assert view._left_field.text() == ""
    assert view._state.left_path is None


def test_dispose_is_idempotent(view: CompareView) -> None:
    view.dispose()
    view.dispose()

    assert view._state.phase.name == "IDLE" or view._state.phase.name == "CANCELLED"
