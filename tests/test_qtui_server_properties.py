"""Qt server.properties 视图测试：表单构建、读取、保存与生命周期。"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

import pytest
from PySide6.QtWidgets import QApplication, QCheckBox, QLineEdit

from app.adapters.file_dialogs import FileType
from app.qtui.views.server_properties import ServerPropertiesView
from app.services.execution_runtime import (
    ExecutionRuntime,
    LaneLimits,
)
from app.services.server_properties_service import (
    BOOLEAN_PROPERTIES,
    DEFAULT_SERVER_PROPERTIES,
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


class FakeHost:
    """实现 ServerPropertiesHost 端口的最小测试宿主。"""

    def __init__(self) -> None:
        limits = LaneLimits(max_workers=2, queue_capacity=8)
        self.runtime = ExecutionRuntime(
            io_limits=limits,
            cpu_limits=limits,
        )
        self.infos: list[tuple[str, str]] = []
        self.warns: list[tuple[str, str]] = []
        self.errors: list[tuple[str, str]] = []
        self.logs: list[tuple[str, str]] = []
        self.picked: Optional[str] = None

    def translate(self, key: str, default: str = "", **kwargs: Any) -> str:
        del kwargs
        return default

    def log(self, msg: str, level: str = "INFO") -> None:
        self.logs.append((msg, level))

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

    @property
    def execution_runtime(self) -> ExecutionRuntime:
        return self.runtime

    def close(self) -> None:
        self.runtime.shutdown(wait=True, timeout=5.0)


@pytest.fixture
def host(qt_app: object) -> Iterator[FakeHost]:
    del qt_app
    fake = FakeHost()
    yield fake
    fake.close()


@pytest.fixture
def view(host: FakeHost) -> Iterator[ServerPropertiesView]:
    yield ServerPropertiesView(host)


def test_view_builds_default_form(view: ServerPropertiesView) -> None:
    assert set(view._fields.keys()) == set(DEFAULT_SERVER_PROPERTIES.keys())
    actions = view.get_top_actions()
    assert [action.label for action in actions] == ["读取配置"]


def test_view_pick_directory_updates_path_field(
    view: ServerPropertiesView,
    host: FakeHost,
    tmp_path: Path,
) -> None:
    host.picked = str(tmp_path)

    view._pick()

    assert view._path_field.text() == str(tmp_path)


def test_view_load_reads_real_file(
    view: ServerPropertiesView,
    host: FakeHost,
    tmp_path: Path,
) -> None:
    (tmp_path / "server.properties").write_text(
        "online-mode=false\nserver-port=25599\n",
        encoding="utf-8",
    )
    view._path_field.setText(str(tmp_path))

    view._load()

    assert _wait_until(lambda: not view._busy)
    assert host.infos == [("成功", "已读取 server.properties。")]
    assert view._path == tmp_path
    online_mode = view._fields["online-mode"]
    assert isinstance(online_mode, QCheckBox)
    assert online_mode.isChecked() is False
    port_field = view._fields["server-port"]
    assert isinstance(port_field, QLineEdit)
    assert port_field.text() == "25599"


def test_view_save_writes_real_file(
    view: ServerPropertiesView,
    host: FakeHost,
    tmp_path: Path,
) -> None:
    view._path_field.setText(str(tmp_path))
    port_field = view._fields["server-port"]
    assert isinstance(port_field, QLineEdit)
    port_field.setText("25565")

    view._save()

    assert _wait_until(lambda: not view._busy)
    assert host.infos == [("成功", "server.properties 已保存。")]
    written = (tmp_path / "server.properties").read_text(encoding="utf-8")
    assert "server-port=25565" in written


def test_view_save_warns_without_path(
    view: ServerPropertiesView,
    host: FakeHost,
) -> None:
    view._path_field.setText("")

    view._save()

    assert host.warns == [("提示", "请先选择保存位置。")]
    assert not view._busy


def test_view_busy_state_disables_fields(
    view: ServerPropertiesView,
    host: FakeHost,
    tmp_path: Path,
) -> None:
    (tmp_path / "server.properties").write_text(
        "server-port=25599\n",
        encoding="utf-8",
    )
    view._path_field.setText(str(tmp_path))

    view._set_busy(True)

    assert not view._path_field.isEnabled()
    assert not view._browse_button.isEnabled()
    assert not view._save_button.isEnabled()
    assert all(not control.isEnabled() for control in view._fields.values())

    view._set_busy(False)
    assert view._path_field.isEnabled()


def test_view_dispose_is_idempotent(view: ServerPropertiesView) -> None:
    view.dispose()
    view.dispose()

    assert view._disposed is True
    assert view._busy is False


def test_view_rejects_actions_after_dispose(
    view: ServerPropertiesView,
    host: FakeHost,
) -> None:
    view.dispose()

    view._load()
    view._save()

    assert not view._busy
    assert host.infos == []
    assert host.warns == []


def test_boolean_property_maps_to_checkbox(view: ServerPropertiesView) -> None:
    for key in BOOLEAN_PROPERTIES:
        field = view._fields[key]
        assert field.__class__.__name__ == "QCheckBox"
