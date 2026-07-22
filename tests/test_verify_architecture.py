"""架构自动验收脚本的静态检查项测试。"""
from __future__ import annotations

import subprocess

from scripts import verify_architecture
from scripts.verify_architecture import (
    check_app_threadpools,
    check_core_threadpool_bounds,
    check_dependency_direction,
    check_forbidden_runtime_dependencies,
    check_region_map_package,
    check_translation_parity,
    check_world_index_cache,
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
    ]
    failed = [item for item in checks if not item.ok]
    assert failed == [], failed


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
