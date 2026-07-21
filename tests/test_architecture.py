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


def test_services_do_not_import_ui_implementations() -> None:
    violations = []
    for source_path in (PROJECT_ROOT / "app/services").rglob("*.py"):
        source = source_path.read_text(encoding="utf-8")
        if "app.ui" in source:
            violations.append(str(source_path.relative_to(PROJECT_ROOT)))

    assert violations == [], f"service 反向导入 UI: {violations}"


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


def test_window_manager_uses_explicit_responsive_shell_host() -> None:
    source = (
        PROJECT_ROOT / "app/core/window_manager.py"
    ).read_text(encoding="utf-8")

    assert "ResponsiveShellHost" in source
    assert "WindowManagerDependencies" in source
    assert "self.app =" not in source
    assert "self.app." not in source
    for private_control in (
        "self.app._sidebar",
        "self.app._main_row",
        "self.app._shell",
        "self.app._scrollable_content",
        "self.app._content",
        "self.app._heartbeat_active",
        "self.app._hang_detector_active",
    ):
        assert private_control not in source


def test_views_with_shell_actions_declare_public_action_provider() -> None:
    view_paths = (
        "app/ui/views/explorer/explorer_view.py",
        "app/ui/views/migrator.py",
        "app/ui/views/save_repair.py",
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


def test_config_service_has_no_hidden_singleton_lifetime() -> None:
    source = (
        PROJECT_ROOT / "app/services/config_service.py"
    ).read_text(encoding="utf-8")

    assert "def __new__" not in source
    assert "_instance" not in source


def test_i18n_service_has_no_hidden_singleton_lifetime() -> None:
    source = (
        PROJECT_ROOT / "app/services/i18n_service.py"
    ).read_text(encoding="utf-8")

    assert "_i18n_service" not in source
    assert "def get_i18n(" not in source


def test_item_and_texture_services_are_application_scoped() -> None:
    for relative_path in (
        "app/services/item_service.py",
        "app/services/texture_service.py",
    ):
        source = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        assert "def __new__" not in source, relative_path
        assert "_instance" not in source, relative_path

    view_sources = "\n".join(
        source_path.read_text(encoding="utf-8")
        for source_path in (PROJECT_ROOT / "app/ui/views").rglob("*.py")
    )
    assert "get_item_service" not in view_sources
    assert "get_texture_service" not in view_sources


def test_application_does_not_mutate_migrator_private_controls() -> None:
    application_source = (
        PROJECT_ROOT / "app" / "application.py"
    ).read_text(encoding="utf-8")

    assert "_update_migrator_field" not in application_source
    assert '"_src_field"' not in application_source
    assert '"_dest_field"' not in application_source
    assert '"_batch_dir_field"' not in application_source
    assert "set_path_value" in application_source


def test_dialog_manager_does_not_hold_application() -> None:
    source = (
        PROJECT_ROOT / "app/core/dialog_manager.py"
    ).read_text(encoding="utf-8")

    assert "self.app" not in source
    assert "DialogManagerDependencies" in source
    assert "switch_view" in source
    assert "remove_view" in source
    assert "tkinter" not in source
    assert "FileDialogPort" in source


def test_progress_manager_does_not_hold_application() -> None:
    source = (
        PROJECT_ROOT / "app/core/progress_manager.py"
    ).read_text(encoding="utf-8")

    assert "self.app" not in source
    assert "translate" in source


def test_gui_optimizer_does_not_hold_application() -> None:
    source = (
        PROJECT_ROOT / "app/core/gui_optimizer.py"
    ).read_text(encoding="utf-8")

    assert "self.app" not in source
    assert "GUIOptimizerDependencies" in source


def test_settings_view_uses_explicit_shell_ports() -> None:
    source = (
        PROJECT_ROOT / "app/ui/views/settings.py"
    ).read_text(encoding="utf-8")

    assert "SettingsViewDependencies" in source
    assert "from app.application" not in source
    assert "self.app" not in source
    assert "._config" not in source
    assert "_heartbeat_active" not in source
    assert "configure_performance_monitor" in source


def test_application_has_no_dead_manager_state_aliases() -> None:
    source = (
        PROJECT_ROOT / "app/application.py"
    ).read_text(encoding="utf-8")

    assert "def views(" not in source
    assert "def _heartbeat_active(" not in source
    assert "def _hang_detector_active(" not in source
    assert "def notification_manager(" not in source


def test_views_do_not_call_application_private_members() -> None:
    violations = []
    for source_path in (PROJECT_ROOT / "app/ui/views").rglob("*.py"):
        source = source_path.read_text(encoding="utf-8")
        if "self.app._" in source:
            violations.append(str(source_path.relative_to(PROJECT_ROOT)))

    assert violations == []


def test_entrypoint_does_not_monkey_patch_flet_classes() -> None:
    source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")

    assert "_patch_flet_api" not in source
    assert "ft.Dropdown =" not in source
    assert "ft.Image =" not in source
    assert "ft.Page.run_task =" not in source


def test_migration_controller_does_not_hold_application() -> None:
    controller_path = (
        PROJECT_ROOT / "app" / "controllers" / "migration_controller.py"
    )
    source = controller_path.read_text(encoding="utf-8")

    assert "self.app" not in source
    assert "app: Any" not in source
    assert "app.ui" not in source
    assert "MigrationControllerDependencies" in source


def test_region_map_service_is_not_a_global_singleton() -> None:
    shim_path = PROJECT_ROOT / "app" / "services" / "region_map_service.py"
    service_path = (
        PROJECT_ROOT / "app" / "services" / "region_map" / "service.py"
    )
    source = (
        shim_path.read_text(encoding="utf-8")
        + "\n"
        + service_path.read_text(encoding="utf-8")
    )

    assert "def __new__" not in source
    assert "_region_map_service_instance" not in source
    assert "get_region_map_service" not in source
    assert "def close(self)" in source

    map_view_source = (
        PROJECT_ROOT / "app/ui/views/explorer/map/mca_map_view.py"
    ).read_text(encoding="utf-8")
    explorer_source = (
        PROJECT_ROOT / "app/ui/views/explorer/explorer_view.py"
    ).read_text(encoding="utf-8")
    application_source = (
        PROJECT_ROOT / "app/application.py"
    ).read_text(encoding="utf-8")
    assert "get_region_map_service" not in map_view_source
    assert "get_region_map_service" not in explorer_source
    assert "create_region_map_service" in application_source


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


def test_region_tab_delegates_fullscreen_overlay_lifecycle() -> None:
    region_tab_source = (
        PROJECT_ROOT / "app/ui/views/explorer/region_tab.py"
    ).read_text(encoding="utf-8")
    explorer_source = (
        PROJECT_ROOT / "app/ui/views/explorer/explorer_view.py"
    ).read_text(encoding="utf-8")

    assert "MapFullscreenController" in region_tab_source
    assert "page.overlay" not in region_tab_source
    assert "threading.Thread" not in region_tab_source
    assert "_dispose_region_tab()" in explorer_source
