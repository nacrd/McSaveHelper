"""FeatureContext and composition-root size checks."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

from app.ui.feature_context import (
    FeatureContext,
    FeatureDialogPort,
    FeatureFileDialogPort,
    FeatureHost,
    FeaturePagePort,
    FeatureProgressPort,
    FeatureRuntimePort,
    FeatureTranslationPort,
    MigrationCommands,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_application_module_stays_under_250_lines() -> None:
    lines = (PROJECT_ROOT / "app" / "application.py").read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(lines) < 250


def test_views_do_not_type_application_union() -> None:
    views_root = PROJECT_ROOT / "app" / "ui" / "views"
    offenders: list[str] = []
    for path in views_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "Application | FeatureContext" in source:
            offenders.append(path.relative_to(PROJECT_ROOT).as_posix())
        if "from app.application import Application" in source:
            offenders.append(path.relative_to(PROJECT_ROOT).as_posix())
    assert offenders == []


def test_feature_context_delegates_host_ports() -> None:
    calls: list[str] = []
    commands = MigrationCommands(
        start=lambda: calls.append("start"),
        cancel=lambda: True,
        choose_destination=lambda: calls.append("dest"),
        choose_batch_directory=lambda: calls.append("batch"),
        close=lambda: calls.append("close"),
    )

    host = SimpleNamespace(
        page=object(),
        migration_commands=commands,
        config=object(),
        migration=object(),
        uuid=object(),
        item=object(),
        texture=object(),
        execution_runtime=object(),
        ui_delivery=object(),
        backup=object(),
        save_repair=object(),
        world_compare=object(),
        world_transactions=object(),
        world_repository=object(),
        world_stats=object(),
        cache_registry=object(),
        current_save_path="C:/tmp/world",
        save_context_manager=object(),
        view_manager=object(),
        translate=lambda key, default="", **kwargs: default or key,
        log=lambda msg, level="INFO": calls.append(f"log:{level}"),
        info_dialog=lambda title, message: calls.append("info"),
        warn_dialog=lambda title, message: calls.append("warn"),
        error_dialog=lambda *args, **kwargs: calls.append("error"),
        handle_exception=lambda *args, **kwargs: calls.append("exc"),
        pick_directory=lambda: "dir",
        pick_file=lambda *args, **kwargs: "file",
        pick_files=lambda *args, **kwargs: ["file"],
        save_file=lambda *args, **kwargs: "out",
        show_progress=lambda task_name="": calls.append("show"),
        hide_progress=lambda: calls.append("hide"),
        update_progress_with_task=lambda task, value: calls.append("progress"),
        create_region_map_service=lambda: "map",
        update_uuid_mappings=lambda mappings: calls.append("uuid"),
    )

    ctx = FeatureContext(cast(FeatureHost, host))
    assert ctx.translate("k", "v") == "v"
    assert ctx.pick_directory() == "dir"
    assert ctx.create_region_map_service() == "map"
    assert ctx.current_save_path == "C:/tmp/world"
    assert ctx.ui_delivery is host.ui_delivery
    assert ctx.backup is host.backup
    assert ctx.save_repair is host.save_repair
    assert ctx.world_compare is host.world_compare
    assert ctx.world_transactions is host.world_transactions
    assert ctx.world_repository is host.world_repository
    assert ctx.world_stats is host.world_stats
    assert ctx.cache_registry is host.cache_registry
    assert ctx.migration_commands is commands
    ctx.show_progress("task")
    assert "show" in calls
    assert not hasattr(ctx, "start")
    assert not hasattr(ctx, "set_dest")
    assert not hasattr(ctx, "set_batch_dir")
    assert not hasattr(ctx, "services")

    translation: FeatureTranslationPort = ctx
    dialogs: FeatureDialogPort = ctx
    file_dialogs: FeatureFileDialogPort = ctx
    progress: FeatureProgressPort = ctx
    runtime: FeatureRuntimePort = ctx
    page: FeaturePagePort = ctx
    assert translation.translate("k", "v") == "v"
    assert dialogs is ctx
    assert file_dialogs.pick_directory() == "dir"
    assert progress is ctx
    assert runtime.execution_runtime is host.execution_runtime
    assert page.page is host.page
