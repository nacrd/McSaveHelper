"""架构自动验收脚本的静态检查项测试。"""
from __future__ import annotations

import json
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
    run_mca_benchmark,
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
