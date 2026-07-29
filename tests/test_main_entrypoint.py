from pathlib import Path

import pytest

import main as entrypoint


def test_consume_console_flag_removes_all_occurrences() -> None:
    argv = ["MCSaveHelper.exe", "--console", "world", "--console"]

    consumed = entrypoint._consume_console_flag(argv)

    assert consumed is True
    assert argv == ["MCSaveHelper.exe", "world"]


def test_main_configures_console_before_running_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    argv = ["MCSaveHelper.exe", "--console"]
    monkeypatch.setattr(
        entrypoint,
        "_setup_console",
        lambda: events.append("console"),
    )
    monkeypatch.setattr(
        entrypoint,
        "_run_application",
        lambda: events.append("application"),
    )

    exit_code = entrypoint.main(argv)

    assert exit_code == 0
    assert argv == ["MCSaveHelper.exe"]
    assert events == ["console", "application"]


def test_main_reports_missing_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages: list[str] = []

    def raise_import_error() -> None:
        raise ImportError("missing-package")

    monkeypatch.setattr(entrypoint, "_run_application", raise_import_error)
    monkeypatch.setattr(entrypoint, "_write_error_log", messages.append)

    exit_code = entrypoint.main(["MCSaveHelper.exe"])

    assert exit_code == 1
    assert len(messages) == 1
    assert "missing-package" in messages[0]
    assert "pip install -r requirements.txt" in messages[0]


def test_main_records_unexpected_startup_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages: list[str] = []

    def raise_runtime_error() -> None:
        raise RuntimeError("startup failed")

    monkeypatch.setattr(entrypoint, "_run_application", raise_runtime_error)
    monkeypatch.setattr(entrypoint, "_write_error_log", messages.append)

    exit_code = entrypoint.main(["MCSaveHelper.exe"])

    assert exit_code == 1
    assert len(messages) == 1
    assert "RuntimeError: startup failed" in messages[0]


def test_write_error_log_uses_configured_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "startup_error.log"
    monkeypatch.setattr(entrypoint, "_get_log_path", lambda: log_path)

    entrypoint._write_error_log("failure details")

    assert log_path.read_text(encoding="utf-8") == "failure details"
