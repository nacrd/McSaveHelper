"""FeatureContext and composition-root size checks."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.ui.feature_context import FeatureContext


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

    host = SimpleNamespace(
        page=object(),
        services=SimpleNamespace(),
        config=object(),
        migration=object(),
        uuid=object(),
        item=object(),
        texture=object(),
        execution_runtime=object(),
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
        start=lambda: calls.append("start"),
        set_dest=lambda: calls.append("dest"),
        set_batch_dir=lambda: calls.append("batch"),
    )

    ctx = FeatureContext(host)  # type: ignore[arg-type]
    assert ctx.translate("k", "v") == "v"
    assert ctx.pick_directory() == "dir"
    assert ctx.create_region_map_service() == "map"
    assert ctx.current_save_path == "C:/tmp/world"
    ctx.show_progress("task")
    ctx.start()
    assert "show" in calls
    assert "start" in calls
