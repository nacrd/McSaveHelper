"""Architecture boundaries that protect the reusable core."""
from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_core_does_not_import_application_layer() -> None:
    violations = []
    for source_path in (PROJECT_ROOT / "core").rglob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported = [node.module or ""]
            else:
                continue
            if any(name == "app" or name.startswith("app.") for name in imported):
                violations.append(str(source_path.relative_to(PROJECT_ROOT)))

    assert violations == [], f"core 反向导入 app: {sorted(set(violations))}"


def test_region_editor_compatibility_factory_returns_scoped_instances() -> None:
    from app.services.region_editor_service import get_region_editor_service
    from core.mca import RegionEditor

    first = get_region_editor_service()
    second = get_region_editor_service()

    assert isinstance(first, RegionEditor)
    assert first is not second


def test_save_context_manager_has_no_ui_or_application_dependency() -> None:
    manager_path = PROJECT_ROOT / "app" / "core" / "save_context_manager.py"
    source = manager_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = []
    accessed_attributes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported_modules.append(node.module or "")
        elif isinstance(node, ast.Attribute):
            accessed_attributes.append(node.attr)

    assert not any(name == "flet" or name.startswith("flet.") for name in imported_modules)
    assert "app.application" not in imported_modules
    assert "app" not in accessed_attributes
    assert not {"_sidebar", "_content", "_top_actions", "views"}.intersection(
        accessed_attributes
    )


def test_view_manager_does_not_know_concrete_views_or_private_commands() -> None:
    manager_path = PROJECT_ROOT / "app" / "core" / "view_manager.py"
    source = manager_path.read_text(encoding="utf-8")

    assert "app.ui.views" not in source
    assert "self.app" not in source
    assert "app._content" not in source
    assert "app._top_actions" not in source
    assert "ViewManagerDependencies" in source
    assert "ViewHost" in source
    assert "_get_top_actions" not in source
    for private_command in (
        "_analyze_world_stats",
        "_start_entity_block_search",
        "_refresh_map",
        "_start_detect",
        "_start_export",
        "_compare",
        "_import_lang",
    ):
        assert private_command not in source


def test_views_with_shell_actions_declare_public_action_provider() -> None:
    view_paths = (
        "app/ui/views/explorer/explorer_view.py",
        "app/ui/views/migrator.py",
        "app/ui/views/save_repair.py",
        "app/ui/views/map_export.py",
        "app/ui/views/compare.py",
        "app/ui/views/mappings.py",
        "app/ui/views/server_properties.py",
    )
    for relative_path in view_paths:
        tree = ast.parse(
            (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        )
        method_names = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
        }
        assert "get_top_actions" in method_names, relative_path


def test_application_does_not_construct_partial_services() -> None:
    application_path = PROJECT_ROOT / "app" / "application.py"
    source = application_path.read_text(encoding="utf-8")

    assert "_init_services" not in source
    assert ".__new__(" not in source
    assert "create_app_services" in source


def test_migration_controller_does_not_hold_application() -> None:
    controller_path = (
        PROJECT_ROOT / "app" / "controllers" / "migration_controller.py"
    )
    source = controller_path.read_text(encoding="utf-8")

    assert "self.app" not in source
    assert "app: Any" not in source
    assert "MigrationControllerDependencies" in source


def test_region_map_service_is_not_a_global_singleton() -> None:
    service_path = PROJECT_ROOT / "app" / "services" / "region_map_service.py"
    source = service_path.read_text(encoding="utf-8")

    assert "def __new__" not in source
    assert "_region_map_service_instance" not in source
    assert "def close(self)" in source


def test_lightweight_operation_services_are_not_global_singletons() -> None:
    service_paths = (
        "app/services/world_compare_service.py",
        "app/services/world_stats_service.py",
        "app/services/server_properties_service.py",
        "app/services/block_data_service.py",
    )
    forbidden_names = (
        "_compare_service",
        "_world_stats_service",
        "_server_properties_service",
        "_block_data_service",
    )
    for relative_path in service_paths:
        source = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        assert not any(
            f"{name}:" in source or f"{name} =" in source
            for name in forbidden_names
        ), relative_path


def test_nbt_managers_do_not_reach_through_explorer_context() -> None:
    manager_paths = (
        "app/ui/views/explorer/nbt/nbt_stage_manager.py",
        "app/ui/views/explorer/nbt/nbt_commit_handler.py",
        "app/ui/views/explorer/nbt/nbt_data_loader.py",
        "app/ui/views/explorer/nbt/chunk_operations.py",
    )
    for relative_path in manager_paths:
        source = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        assert "context: Any" not in source, relative_path
        assert "self.ctx" not in source, relative_path
        assert "_staged_nbt_changes" not in source, relative_path


def test_map_view_uses_pure_core_viewport_math() -> None:
    viewport_path = PROJECT_ROOT / "core" / "mca" / "viewport.py"
    viewport_source = viewport_path.read_text(encoding="utf-8")
    map_view_source = (
        PROJECT_ROOT
        / "app"
        / "ui"
        / "views"
        / "explorer"
        / "map"
        / "mca_map_view.py"
    ).read_text(encoding="utf-8")

    assert "import flet" not in viewport_source
    assert "from app" not in viewport_source
    assert "McaViewport" in map_view_source
    assert "McaMapSelection" in map_view_source
    assert "math." not in map_view_source
    assert "_zoom_anim_target_scale" not in map_view_source
