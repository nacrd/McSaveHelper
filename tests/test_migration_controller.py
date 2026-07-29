from pathlib import Path

from app.controllers.migration_controller import (
    MigrationController,
    MigrationControllerDependencies,
)
from app.services.config_service import ConfigService


class FakeMigrationService:
    def __init__(self) -> None:
        self.batch_worlds = []
        self.single_calls = []
        self.opened_paths = []

    def run_single(self, **kwargs):
        self.single_calls.append(kwargs)
        return str(Path(kwargs["dest"]) / kwargs["world_name"])

    def open_folder(self, path: str) -> None:
        self.opened_paths.append(path)

    def run_batch(self, **kwargs):
        del kwargs
        return {
            "task-1": {"success": True},
            "task-2": {"success": False, "error": "failed"},
            "task-3": {"success": False, "cancelled": True},
        }


def _translate(key: str, default: str = "", **kwargs) -> str:
    del key
    return default.format(**kwargs)


def _create_controller(config, migration, state, start_worker=None):
    def record(name):
        return lambda *args, **kwargs: state.setdefault(name, []).append(
            (args, kwargs)
        )

    dependencies = MigrationControllerDependencies(
        config=config,
        migration=migration,
        translate=_translate,
        warn_dialog=record("warnings"),
        error_dialog=record("errors"),
        handle_exception=record("exceptions"),
        show_success=record("successes"),
        set_start_enabled=lambda enabled: state.setdefault(
            "enabled", []
        ).append(enabled),
        update_page=lambda: state.setdefault("updates", []).append(True),
        log=lambda message, level: state.setdefault("logs", []).append(
            (message, level)
        ),
        log_header=lambda message: state.setdefault("headers", []).append(
            message
        ),
        update_progress=lambda value: state.setdefault("progress", []).append(
            value
        ),
        set_progress_label=lambda label: state.setdefault("labels", []).append(
            label
        ),
        set_progress_value=lambda value: state.setdefault(
            "progress_values", []
        ).append(value),
        start_worker=start_worker or (
            lambda operation, target, argument: None
        ),
    )
    return MigrationController(dependencies)


def test_controller_rejects_missing_source_without_starting_worker(
    tmp_path: Path,
) -> None:
    config = ConfigService(tmp_path / "config")
    state = {}
    workers = []
    controller = _create_controller(
        config,
        FakeMigrationService(),
        state,
        start_worker=lambda operation, target, argument: workers.append(
            (operation, target, argument)
        ),
    )

    controller.start()

    assert workers == []
    assert state["warnings"]
    assert "请先" in state["warnings"][0][0][1]


def test_controller_selects_single_worker_and_injects_destination(
    tmp_path: Path,
) -> None:
    config = ConfigService(tmp_path / "config")
    config.migration.src_path = str(tmp_path / "source")
    config.migration.dest_path = str(tmp_path / "output")
    state = {}
    workers = []
    controller = _create_controller(
        config,
        FakeMigrationService(),
        state,
        start_worker=lambda operation, target, argument: workers.append(
            (operation, target.__name__, argument)
        ),
    )

    controller.start()

    assert workers == [
        ("migration_single", "run_single_thread", str(tmp_path / "output"))
    ]
    assert state["enabled"] == [False]
    assert state["updates"] == [True]


def test_controller_rejects_missing_destination(tmp_path: Path) -> None:
    config = ConfigService(tmp_path / "config")
    config.migration.src_path = str(tmp_path / "source")
    state = {}
    workers = []
    controller = _create_controller(
        config,
        FakeMigrationService(),
        state,
        start_worker=lambda operation, target, argument: workers.append(
            (operation, target, argument)
        ),
    )

    controller.start()

    assert workers == []
    assert "目标输出目录" in state["warnings"][0][0][1]


def test_controller_single_run_reports_success_and_resets_ui(
    tmp_path: Path,
) -> None:
    config = ConfigService(tmp_path / "config")
    config.migration.src_path = str(tmp_path / "source")
    config.migration.world_name = "converted"
    migration = FakeMigrationService()
    state = {}
    controller = _create_controller(config, migration, state)

    controller.run_single_thread(str(tmp_path / "output"))

    assert migration.single_calls
    assert state["successes"][0][0][0] == "成功"
    assert "converted" in state["successes"][0][0][1]
    assert state["enabled"][-1] is True
    assert state["progress_values"][-1] == 0


def test_controller_reports_partial_batch_without_success_label(
    tmp_path: Path,
) -> None:
    config = ConfigService(tmp_path / "config")
    state = {}
    controller = _create_controller(config, FakeMigrationService(), state)

    controller.run_batch_thread(str(tmp_path / "output"))

    assert state["labels"][-1] == "批量处理部分完成"
    assert any(level == "WARN" for _, level in state["logs"])
    assert any("取消: 1" in message for message, _ in state["logs"])
