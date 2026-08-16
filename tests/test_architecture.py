"""Architecture boundaries for the Qt application tree."""
from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def test_core_does_not_import_application_layer() -> None:
    offenders = []
    for path in (PROJECT_ROOT / "core").rglob("*.py"):
        if any(name == "app" or name.startswith("app.") for name in _imports(path)):
            offenders.append(path.relative_to(PROJECT_ROOT).as_posix())
    assert offenders == []


def test_services_and_controllers_do_not_import_ui_framework() -> None:
    offenders = []
    for root in (PROJECT_ROOT / "app" / "services", PROJECT_ROOT / "app" / "controllers"):
        for path in root.rglob("*.py"):
            imports = _imports(path)
            if any(
                name == "flet"
                or name.startswith("flet.")
                or name == "app.ui"
                or name.startswith("app.ui.")
                for name in imports
            ):
                offenders.append(path.relative_to(PROJECT_ROOT).as_posix())
    assert offenders == []


def test_qtui_does_not_import_removed_flet_tree() -> None:
    offenders = []
    qt_root = PROJECT_ROOT / "app" / "qtui"
    for path in qt_root.rglob("*.py"):
        imports = _imports(path)
        if any(
            name == "flet"
            or name.startswith("flet.")
            or name == "app.ui"
            or name.startswith("app.ui.")
            for name in imports
        ):
            offenders.append(path.relative_to(PROJECT_ROOT).as_posix())
    assert offenders == []


def test_qt_registry_has_stable_migrated_catalog(qt_app: object) -> None:
    del qt_app
    from app.qtui.registry import create_qt_registry

    registry = create_qt_registry()
    view_ids = [feature.view_id for feature in registry.features]
    assert view_ids[0] == "explorer"
    assert {"migrator", "settings", "server_properties"} <= set(view_ids)
    assert len(view_ids) == len(set(view_ids))


def test_qt_views_expose_disposal_for_owned_background_work() -> None:
    views_root = PROJECT_ROOT / "app" / "qtui" / "views"
    owned = ("explorer.py", "compare.py", "backup_center.py", "save_repair.py")
    for filename in owned:
        source = (views_root / filename).read_text(encoding="utf-8")
        assert "def dispose" in source, filename


def test_save_context_manager_is_framework_neutral() -> None:
    source = (PROJECT_ROOT / "app" / "core" / "save_context_manager.py").read_text(
        encoding="utf-8"
    )
    assert "flet" not in source
    assert "app.ui" not in source
    assert "app.application" not in source


def test_qt_application_is_the_composition_root() -> None:
    source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
    assert "from app.qtui.application import QtApplication" in source
    assert "--flet" not in source
    assert "--qt" not in source


def test_world_writes_use_transaction_boundary() -> None:
    editor = (PROJECT_ROOT / "app/services/region_editor_service.py").read_text(
        encoding="utf-8"
    )
    coordinator = (
        PROJECT_ROOT / "app/qtui/views/region_map_coordinator.py"
    ).read_text(encoding="utf-8")
    assert "world_transactions.mutate" in editor
    assert "RegionDeleteRequest" in coordinator
    assert "_region_delete_controller.start" in coordinator
