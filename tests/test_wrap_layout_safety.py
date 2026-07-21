"""Regression tests for Flutter Wrap/Flex parent-data compatibility."""
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator, cast

import flet as ft

from app.services.backup_service import BackupRecord, BackupService
from app.ui.views.backup_center import BackupCenterView
from app.ui.views.compare import CompareView
from app.ui.views.mappings import MappingsView
from app.ui.views.server_properties import ServerPropertiesView


def _app(**values: object) -> Any:
    defaults: dict[str, object] = {
        "log": lambda message, level="INFO": None,
        "translate": lambda key, default: default,
        "services": SimpleNamespace(backup=BackupService()),
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


def _walk_controls(control: ft.Control) -> Iterator[ft.Control]:
    """Yield a Flet control tree without relying on private internals."""
    yield control
    children = getattr(control, "controls", None)
    if children:
        for child in children:
            yield from _walk_controls(child)
    content = getattr(control, "content", None)
    if isinstance(content, ft.Control):
        yield from _walk_controls(content)


def _assert_wrap_children_do_not_expand(root: ft.Control) -> None:
    for control in _walk_controls(root):
        if not isinstance(control, ft.Row) or not control.wrap:
            continue
        expanded_children = [
            child for child in control.controls if bool(child.expand)
        ]
        assert not expanded_children


def _assert_no_wrap_layouts(root: ft.Control) -> None:
    for control in _walk_controls(root):
        assert not isinstance(control, ft.ResponsiveRow)
        if isinstance(control, ft.Row):
            assert control.wrap is False


def test_path_forms_do_not_put_expanded_fields_in_wraps() -> None:
    compare_view = CompareView(cast(Any, _app()))
    properties_view = ServerPropertiesView(cast(Any, _app()))

    _assert_wrap_children_do_not_expand(compare_view)
    _assert_wrap_children_do_not_expand(properties_view)
    _assert_no_wrap_layouts(properties_view)


def test_backup_row_does_not_mix_wrap_and_flex_parent_data() -> None:
    view = BackupCenterView(cast(Any, _app()))
    record = BackupRecord(
        backup_id="20260721T120000Z-12345678",
        label="测试恢复点",
        world_name="world",
        source_path="C:/world",
        created_at=datetime.now(timezone.utc),
        size_bytes=1,
        file_count=1,
        backup_path=Path("C:/backups/test"),
    )

    row = view._backup_row(record)
    _assert_wrap_children_do_not_expand(row)
    _assert_no_wrap_layouts(row)


def test_reported_top_level_pages_do_not_use_wrap_layouts() -> None:
    app = cast(
        Any,
        _app(
            item=SimpleNamespace(
                get_custom_item_mappings=lambda: {},
            ),
            config=SimpleNamespace(custom_uuid_mappings={}),
            update_uuid_mappings=lambda mappings: None,
        ),
    )
    views = (
        BackupCenterView(app),
        MappingsView(app),
        ServerPropertiesView(app),
    )

    for view in views:
        _assert_no_wrap_layouts(view)
