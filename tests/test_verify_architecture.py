"""架构自动验收脚本的静态检查项测试。"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts import verify_architecture
from scripts.verify_architecture import (
    check_app_threadpools,
    check_core_threadpool_bounds,
    check_dependency_direction,
    check_forbidden_runtime_dependencies,
    check_region_map_package,
    check_translation_parity,
    check_views_use_narrow_host_ports,
    check_world_view_context_lifecycle,
    check_world_index_cache,
    run_mca_benchmark,
    run_source_entrypoint_smoke,
)


def test_architecture_static_acceptance_checks_pass() -> None:
    checks = [
        check_dependency_direction(),
        check_app_threadpools(),
        check_core_threadpool_bounds(),
        check_forbidden_runtime_dependencies(),
        check_region_map_package(),
        check_world_index_cache(),
        check_translation_parity(),
        check_views_use_narrow_host_ports(),
        check_world_view_context_lifecycle(),
    ]
    failed = [item for item in checks if not item.ok]
    assert failed == [], failed


def _write_view(tmp_path: Path, source: str) -> None:
    views_root = tmp_path / "app" / "qtui" / "views"
    views_root.mkdir(parents=True)
    (views_root / "bad_view.py").write_text(source, encoding="utf-8")


def test_narrow_host_check_rejects_complete_context(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_view(
        tmp_path,
        "from app.ui.feature_context import FeatureContext\n",
    )
    monkeypatch.setattr(verify_architecture, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(verify_architecture, "APP_ROOT", tmp_path / "app")

    result = check_views_use_narrow_host_ports()

    assert result.ok is False
    assert result.detail == "app/qtui/views/bad_view.py"


def test_narrow_host_check_rejects_qualified_application_type(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_view(
        tmp_path,
        "import app.application as application\n"
        "def build(host: application.Application) -> None:\n"
        "    pass\n",
    )
    monkeypatch.setattr(verify_architecture, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(verify_architecture, "APP_ROOT", tmp_path / "app")

    result = check_views_use_narrow_host_ports()

    assert result.ok is False
    assert result.detail == "app/qtui/views/bad_view.py"


def test_world_view_lifecycle_check_rejects_missing_clear_hook(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_view(
        tmp_path,
        "class BadView:\n"
        "    def on_save_selected(self, path: str) -> None:\n"
        "        pass\n",
    )
    monkeypatch.setattr(verify_architecture, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(verify_architecture, "APP_ROOT", tmp_path / "app")

    result = check_world_view_context_lifecycle()

    assert result.ok is False
    assert result.detail == "app/qtui/views/bad_view.py:BadView"


def test_command_timeout_becomes_structured_failure(monkeypatch) -> None:
    def timeout(*args, **kwargs):
        del args, kwargs
        raise subprocess.TimeoutExpired(["pytest"], timeout=1)

    monkeypatch.setattr(verify_architecture.subprocess, "run", timeout)

    result = verify_architecture._run_command(
        "pytest",
        ["pytest"],
        timeout_seconds=1,
    )

    assert result.ok is False
    assert result.detail == "timeout>1s"


def test_source_entrypoint_smoke_imports_main_in_isolated_process(
    monkeypatch,
) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(verify_architecture.subprocess, "run", run)

    result = run_source_entrypoint_smoke()

    assert result.ok is True
    assert result.name == "source_entrypoint_import"
    command, kwargs = calls[0]
    assert command == [verify_architecture.sys.executable, "-c", "import main"]
    assert kwargs["cwd"] == verify_architecture.PROJECT_ROOT
    assert kwargs["timeout"] == 15


def test_source_entrypoint_smoke_reports_import_failure(monkeypatch) -> None:
    completed = subprocess.CompletedProcess(
        args=["python", "-c", "import main"],
        returncode=1,
        stdout="",
        stderr="ImportError: missing flet",
    )
    monkeypatch.setattr(
        verify_architecture.subprocess,
        "run",
        lambda *args, **kwargs: completed,
    )

    result = run_source_entrypoint_smoke()

    assert result.ok is False
    assert result.detail == "ImportError: missing flet"


def test_source_entrypoint_smoke_reports_timeout(monkeypatch) -> None:
    def timeout(*args, **kwargs):
        del args, kwargs
        raise subprocess.TimeoutExpired(["python"], timeout=15)

    monkeypatch.setattr(verify_architecture.subprocess, "run", timeout)

    result = run_source_entrypoint_smoke()

    assert result.ok is False
    assert result.detail == "timeout>15s"


def test_benchmark_invalid_json_becomes_structured_failure(monkeypatch) -> None:
    completed = subprocess.CompletedProcess(
        args=["benchmark"],
        returncode=0,
        stdout="not-json",
        stderr="",
    )
    monkeypatch.setattr(
        verify_architecture.subprocess,
        "run",
        lambda *args, **kwargs: completed,
    )

    result = verify_architecture.run_benchmark()

    assert result.ok is False
    assert result.detail.startswith("invalid json:")


def test_mca_benchmark_consumes_budget_gate_and_cache_hit_metric(monkeypatch) -> None:
    payload = {
        "budgets_ok": True,
        "budget_violations": [],
        "budget_result": {
            "ok": True,
            "violations": [],
            "checked_samples": 3,
        },
        "samples": [
            {
                "size": size,
                "topview": {
                    "cache_hit_p95_ms": 1.0,
                    "cache_hit_count": 3,
                },
                "world_session": {"shell_open_p95_ms": 1.0},
            }
            for size in ("small", "medium", "large")
        ],
    }
    calls: list[list[str]] = []

    def run(command, **kwargs):
        del kwargs
        calls.append(command)
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        )

    monkeypatch.setattr(verify_architecture.subprocess, "run", run)

    result = run_mca_benchmark()

    assert result.ok is True
    command = calls[0]
    assert "scripts.bench_mca" in command
    assert "--check-budgets" in command
    assert "--json" in command


def test_mca_benchmark_rejects_missing_cache_hit_metric(monkeypatch) -> None:
    payload = {
        "budgets_ok": True,
        "budget_violations": [],
        "budget_result": {"ok": True},
        "samples": [
            {"size": size, "topview": {"cache_hit_count": 1}}
            for size in ("small", "medium", "large")
        ],
    }
    completed = subprocess.CompletedProcess(
        args=["bench_mca"],
        returncode=0,
        stdout=json.dumps(payload),
        stderr="",
    )
    monkeypatch.setattr(
        verify_architecture.subprocess,
        "run",
        lambda *args, **kwargs: completed,
    )

    result = run_mca_benchmark()

    assert result.ok is False
    assert "cache hit p95 missing" in result.detail
