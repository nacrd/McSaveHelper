"""Qt 映射管理视图测试：表单构建、映射编辑、查询校验与文件格式。"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

import pytest
from PySide6.QtWidgets import QApplication

from app.adapters.file_dialogs import FileType
from app.qtui.components.uuid_table import read_mappings_file, write_mappings_file
from app.qtui.views.mappings import MappingsView
from app.services.config_service import ConfigService
from app.services.execution_runtime import ExecutionRuntime, LaneLimits
from app.services.item_service import ItemService


_CUSTOM_ITEM = "mod:custom_item"
_CUSTOM_NAME = "自定义物品"


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


class FakeUuidService:
    """最小 UUID 查询服务。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.result: Any = None

    def query_name_history(
        self,
        uuid: str,
        log_callback: Optional[Callable[[str, str], None]] = None,
    ) -> Any:
        self.calls.append((uuid, log_callback))
        return self.result


class FakeHost:
    """实现 MappingsHost 端口的最小测试宿主。"""

    def __init__(self, tmp_path: Path) -> None:
        limits = LaneLimits(max_workers=2, queue_capacity=8)
        self.runtime = ExecutionRuntime(io_limits=limits, cpu_limits=limits)
        self.config = ConfigService(tmp_path / "config")
        self.item = ItemService()
        self.texture: Any = None
        self.uuid = FakeUuidService()
        self.errors: list[tuple[str, str]] = []
        self.infos: list[tuple[str, str]] = []

    def translate(self, key: str, default: str = "", **kwargs: Any) -> str:
        del kwargs
        return default

    def log(self, msg: str, level: str = "INFO") -> None:
        del msg, level

    def info_dialog(self, title: str, message: str) -> None:
        self.infos.append((title, message))

    def warn_dialog(self, title: str, message: str) -> None:
        del title, message

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

    def close(self) -> None:
        self.runtime.shutdown(wait=True, timeout=5.0)


@pytest.fixture
def host(qt_app: object, tmp_path: Path) -> Iterator[FakeHost]:
    del qt_app
    fake = FakeHost(tmp_path)
    yield fake
    fake.close()


@pytest.fixture
def view(host: FakeHost) -> Iterator[MappingsView]:
    yield MappingsView(host)


def test_view_builds_with_top_action(view: MappingsView) -> None:
    actions = view.get_top_actions()
    assert [action.label for action in actions] == ["导入语言文件"]
    assert view._item_table.rowCount() == 1  # 空状态占位行


def test_uuid_table_edit_updates_config(
    view: MappingsView,
    host: FakeHost,
) -> None:
    view._table._add_row()
    name_field, uuid_field, _row = view._table._rows[0]
    name_field.setText("Steve")
    uuid_field.setText("00000000-0000-0000-0000-000000000001")

    assert host.config.custom_uuid_mappings == {
        "Steve": "00000000-0000-0000-0000-000000000001"
    }
    assert view._table.get_mappings()["Steve"] == (
        "00000000-0000-0000-0000-000000000001"
    )


def test_uuid_query_invalid_input_shows_hint(view: MappingsView) -> None:
    view._uuid_query_field.setText("not-a-uuid")

    view._on_uuid_query()

    assert "UUID 格式无效" in view._uuid_query_result.text()


def test_uuid_query_valid_input_calls_service(
    view: MappingsView,
    host: FakeHost,
) -> None:
    view._uuid_query_field.setText("00000000-0000-0000-0000-000000000001")

    view._on_uuid_query()

    assert _wait_until(lambda: bool(host.uuid.calls))
    assert host.uuid.calls[0][0] == "00000000000000000000000000000001"


def test_add_item_mapping_renders_row(view: MappingsView, host: FakeHost) -> None:
    view._item_id_field.setText(_CUSTOM_ITEM)
    view._item_name_field.setText(_CUSTOM_NAME)

    view._add_item_mapping()

    assert host.item.get_custom_item_mappings()[_CUSTOM_ITEM] == _CUSTOM_NAME
    assert view._item_table.rowCount() == 1
    assert "已添加" in view._item_mapping_status.text()


def test_add_item_mapping_warns_on_empty(view: MappingsView, host: FakeHost) -> None:
    view._item_id_field.setText("  ")

    view._add_item_mapping()

    assert "不能为空" in view._item_mapping_status.text()
    assert host.item.get_custom_item_mappings() == {}


def test_delete_item_mapping(view: MappingsView, host: FakeHost) -> None:
    host.item.set_item_mapping(_CUSTOM_ITEM, _CUSTOM_NAME)
    view._render_item_table("")

    view._delete_item_mapping(_CUSTOM_ITEM)

    assert host.item.get_custom_item_mappings() == {}


def test_item_search_filters_rows(view: MappingsView, host: FakeHost) -> None:
    host.item.set_item_mapping("mod:sword", "剑")
    host.item.set_item_mapping("mod:pickaxe", "镐")
    view._item_search_field.setText("sword")

    view._on_item_search()

    assert view._item_table.rowCount() == 1
    assert view._item_table.item(0, 0).text() == "mod:sword"


def test_refresh_mappings_reloads_table(view: MappingsView, host: FakeHost) -> None:
    host.config.custom_uuid_mappings = {"Alex": "10000000-0000-0000-0000-000000000001"}

    view.refresh_mappings()

    assert view._table.get_mappings()["Alex"] == (
        "10000000-0000-0000-0000-000000000001"
    )


def test_dispose_is_idempotent(view: MappingsView) -> None:
    view.dispose()
    view.dispose()

    assert view._state.is_disposed is True


def test_mappings_file_roundtrip(tmp_path: Path) -> None:
    source = tmp_path / "mappings.txt"
    source.write_text(
        "Steve 00000000-0000-0000-0000-000000000001\n"
        "# 注释行\n"
        "Alex 10000000-0000-0000-0000-000000000002\n",
        encoding="utf-8",
    )

    loaded = read_mappings_file(source)

    assert loaded == {
        "Steve": "00000000-0000-0000-0000-000000000001",
        "Alex": "10000000-0000-0000-0000-000000000002",
    }

    output = tmp_path / "out.txt"
    written = write_mappings_file(output, loaded)
    assert written == 2
    assert read_mappings_file(output) == loaded
