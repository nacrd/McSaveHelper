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
        start_worker=start_worker or (lambda target, argument: None),
    )
    return MigrationController(dependencies)


def test_controller_rejects_missing_source_without_starting_worker(
    tmp_path: Path,
) -> None:
    ConfigService._instance = None
    config = ConfigService(tmp_path / "config")
    state = {}
    workers = []
    controller = _create_controller(
        config,
        FakeMigrationService(),
        state,
        start_worker=lambda target, argument: workers.append((target, argument)),
    )

    controller.start()

    assert workers == []
    assert state["warnings"]
    assert "请先" in state["warnings"][0][0][1]
    ConfigService._instance = None


def test_controller_selects_single_worker_and_injects_destination(
    tmp_path: Path,
) -> None:
    ConfigService._instance = None
    config = ConfigService(tmp_path / "config")
    config.migration.src_path = str(tmp_path / "source")
    config.migration.dest_path = str(tmp_path / "output")
    state = {}
    workers = []
    controller = _create_controller(
        config,
        FakeMigrationService(),
        state,
        start_worker=lambda target, argument: workers.append(
            (target.__name__, argument)
        ),
    )

    controller.start()

    assert workers == [
        ("run_single_thread", str(tmp_path / "output"))
    ]
    assert state["enabled"] == [False]
    assert state["updates"] == [True]
    ConfigService._instance = None


def test_controller_single_run_reports_success_and_resets_ui(
    tmp_path: Path,
) -> None:
    ConfigService._instance = None
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
    ConfigService._instance = None
