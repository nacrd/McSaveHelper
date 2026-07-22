"""架构重构完成后的自动验收入口。

聚合依赖方向、并发边界、缓存预算与 pytest 关键门禁，输出机器可读结果。
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = PROJECT_ROOT / "app"
CORE_ROOT = PROJECT_ROOT / "core"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@dataclass(frozen=True)
class CheckResult:
    """单项验收结果。"""

    name: str
    ok: bool
    detail: str


def _iter_py_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        yield path


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(
        path.read_text(encoding="utf-8-sig"),
        filename=str(path),
    )
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _resolved_imports(path: Path) -> set[str]:
    """返回包含相对导入解析结果的模块名集合。"""
    tree = ast.parse(
        path.read_text(encoding="utf-8-sig"),
        filename=str(path),
    )
    relative_parts = path.relative_to(PROJECT_ROOT).with_suffix("").parts
    package_parts = relative_parts[:-1]
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level == 0:
            if node.module:
                names.add(node.module)
            continue
        base = list(package_parts[: len(package_parts) - node.level + 1])
        if node.module:
            base.extend(node.module.split("."))
            names.add(".".join(base))
        else:
            names.update(
                ".".join([*base, alias.name]) for alias in node.names
            )
    return names


def check_dependency_direction() -> CheckResult:
    violations: list[str] = []
    rules = (
        (CORE_ROOT, lambda name: name == "app" or name.startswith("app.")),
        (
            APP_ROOT / "services",
            lambda name: name.startswith("app.ui")
            or name == "flet"
            or name.startswith("flet."),
        ),
        (
            APP_ROOT / "controllers",
            lambda name: name.startswith("app.ui"),
        ),
    )
    for root, is_violation in rules:
        for path in _iter_py_files(root):
            try:
                imports = _resolved_imports(path)
            except (OSError, SyntaxError, UnicodeError) as exc:
                violations.append(f"{path.relative_to(PROJECT_ROOT)} parse: {exc}")
                continue
            for name in imports:
                if is_violation(name):
                    violations.append(
                        f"{path.relative_to(PROJECT_ROOT)} -> {name}"
                    )
    if violations:
        return CheckResult("dependency_direction", False, "; ".join(violations[:8]))
    return CheckResult("dependency_direction", True, "core/services boundaries hold")


def check_app_threadpools() -> CheckResult:
    """应用服务层禁止再直接创建 ThreadPoolExecutor 或裸 threading.Thread。"""
    offenders: list[str] = []
    allowed = {
        "app/services/execution_runtime.py",
    }
    for path in _iter_py_files(APP_ROOT / "services"):
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        if rel in allowed:
            continue
        source = path.read_text(encoding="utf-8-sig")
        if "ThreadPoolExecutor" in source or "threading.Thread(" in source:
            offenders.append(rel)
    if offenders:
        return CheckResult("app_threadpools", False, ", ".join(offenders))
    return CheckResult(
        "app_threadpools",
        True,
        "services use ExecutionRuntime only",
    )


def check_no_private_execution_runtime_fallback() -> CheckResult:
    """禁止应用服务在未注入时静默自建 ExecutionRuntime。"""
    offenders: list[str] = []
    patterns = (
        "or ExecutionRuntime()",
        "execution_runtime or ExecutionRuntime",
        "ExecutionRuntime() if execution_runtime is None",
        "or BackupService(",
    )
    for path in _iter_py_files(APP_ROOT / "services"):
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        if rel == "app/services/execution_runtime.py":
            continue
        source = path.read_text(encoding="utf-8-sig")
        if any(pattern in source for pattern in patterns):
            offenders.append(rel)
        if rel != "app/services/execution_runtime.py" and (
            "ThreadPoolExecutor" in source or "threading.Thread(" in source
        ):
            offenders.append(f"{rel}:pool")
    if offenders:
        return CheckResult(
            "no_private_execution_runtime",
            False,
            ", ".join(offenders),
        )
    return CheckResult(
        "no_private_execution_runtime",
        True,
        "map/texture/repair/avatar require injected runtime",
    )


def check_region_delete_uses_transaction() -> CheckResult:
    """区域删除必须走统一世界事务端口。"""
    region_tab = APP_ROOT / "ui" / "views" / "explorer" / "region_tab.py"
    controller = APP_ROOT / "controllers" / "region_delete_controller.py"
    editor = APP_ROOT / "services" / "region_editor_service.py"
    if (
        not region_tab.is_file()
        or not controller.is_file()
        or not editor.is_file()
    ):
        return CheckResult(
            "region_delete_transaction",
            False, "missing region delete modules",
        )
    tab_source = region_tab.read_text(encoding="utf-8-sig")
    controller_source = controller.read_text(encoding="utf-8-sig")
    editor_source = editor.read_text(encoding="utf-8-sig")
    uses_controller = (
        "RegionDeleteRequest" in tab_source
        and "_region_delete_controller.start" in tab_source
    )
    if not uses_controller:
        return CheckResult(
            "region_delete_transaction",
            False, "region_tab does not route delete through controller",
        )
    if (
        "scope.submit" not in controller_source
        or "delete_region_via_transaction" not in controller_source
    ):
        return CheckResult(
            "region_delete_transaction",
            False, "delete controller does not use runtime transaction",
        )
    if "world_transactions.mutate" not in editor_source:
        return CheckResult(
            "region_delete_transaction",
            False, "delete helper does not call world_transactions.mutate",
        )
    if "reset_region(region_path, backup=True)" in tab_source:
        return CheckResult(
            "region_delete_transaction",
            False,
            "region_tab still uses direct reset_region backup path",
        )
    return CheckResult(
        "region_delete_transaction",
        True,
        "region delete uses WorldTransaction",
    )


def check_views_use_feature_context() -> CheckResult:
    """顶层视图构造参数只接受 FeatureContext，不再联合 Application。"""
    offenders: list[str] = []
    views_root = APP_ROOT / "ui" / "views"
    for path in _iter_py_files(views_root):
        source = path.read_text(encoding="utf-8-sig")
        if "Application | FeatureContext" in source:
            offenders.append(path.relative_to(PROJECT_ROOT).as_posix())
        if 'from app.application import Application' in source:
            offenders.append(path.relative_to(PROJECT_ROOT).as_posix())
    if offenders:
        return CheckResult(
            "views_feature_context",
            False,
            ", ".join(sorted(set(offenders))),
        )
    return CheckResult(
        "views_feature_context",
        True,
        "views depend on FeatureContext only",
    )


def check_core_threadpool_bounds() -> CheckResult:
    """确认 core 内算法线程池都显式提供 max_workers。"""
    offenders: list[str] = []
    for path in _iter_py_files(CORE_ROOT):
        try:
            tree = ast.parse(
                path.read_text(encoding="utf-8-sig"),
                filename=str(path),
            )
        except (OSError, SyntaxError, UnicodeError) as exc:
            offenders.append(f"{path.relative_to(PROJECT_ROOT)}: {exc}")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function_name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else ""
            )
            if function_name != "ThreadPoolExecutor":
                continue
            if not any(keyword.arg == "max_workers" for keyword in node.keywords):
                offenders.append(
                    f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}"
                )
    if offenders:
        return CheckResult("core_threadpool_bounds", False, ", ".join(offenders))
    return CheckResult("core_threadpool_bounds", True, "core pools are explicitly bounded")


def check_forbidden_runtime_dependencies() -> CheckResult:
    """禁止旧 MCA/NBT 第三方解析器重新进入运行时代码。"""
    forbidden = {"anvil_parser", "anvil-parser", "anvil", "nbtlib"}
    offenders: list[str] = []
    for path in _iter_py_files(APP_ROOT) or []:
        try:
            imports = _resolved_imports(path)
        except (OSError, SyntaxError, UnicodeError):
            continue
        if imports.intersection(forbidden):
            offenders.append(str(path.relative_to(PROJECT_ROOT)))
    for path in _iter_py_files(CORE_ROOT):
        try:
            imports = _resolved_imports(path)
        except (OSError, SyntaxError, UnicodeError):
            continue
        if imports.intersection(forbidden):
            offenders.append(str(path.relative_to(PROJECT_ROOT)))
    if offenders:
        return CheckResult("forbidden_runtime_dependencies", False, ", ".join(offenders))
    return CheckResult("forbidden_runtime_dependencies", True, "legacy parsers absent")


def check_region_map_package() -> CheckResult:
    required = [
        APP_ROOT / "services" / "region_map" / "service.py",
        APP_ROOT / "services" / "region_map" / "scan.py",
        APP_ROOT / "services" / "region_map" / "meta.py",
        APP_ROOT / "services" / "region_map" / "topview.py",
        APP_ROOT / "services" / "region_map" / "host.py",
    ]
    missing = [str(path.relative_to(PROJECT_ROOT)) for path in required if not path.exists()]
    if missing:
        return CheckResult("region_map_package", False, f"missing: {', '.join(missing)}")
    try:
        from app.services.execution_runtime import ExecutionRuntime
        from app.services.region_map import RegionMapService

        runtime = ExecutionRuntime()
        service = RegionMapService(runtime)
        service.close()
        runtime.shutdown(wait=False)
    except (ImportError, RuntimeError, ValueError, OSError) as exc:
        return CheckResult("region_map_package", False, f"import/lifecycle: {exc}")
    return CheckResult("region_map_package", True, "scan/meta/topview package present")


def check_world_index_cache() -> CheckResult:
    from app.services.cache_registry import CacheRegistry
    from app.services.world_index_service import WorldIndexRegistry

    max_entries = 2
    cache_registry = CacheRegistry(
        budget_bytes=max_entries * WorldIndexRegistry.ENTRY_BUDGET_BYTES,
    )
    world_indexes = None
    try:
        world_indexes = WorldIndexRegistry(
            max_entries=max_entries,
            cache_registry=cache_registry,
        )
        names = {item.name for item in cache_registry.stats().regions}
        if "world.index" not in names:
            return CheckResult(
                "world_index_cache",
                False,
                "world.index missing from CacheRegistry",
            )
        world_indexes.close()
        names_after_close = {
            item.name for item in cache_registry.stats().regions
        }
        if "world.index" in names_after_close:
            return CheckResult(
                "world_index_cache",
                False,
                "world.index registration leaked after close",
            )
    except (RuntimeError, ValueError, OSError) as exc:
        return CheckResult("world_index_cache", False, str(exc))
    finally:
        if world_indexes is not None:
            world_indexes.close()
        cache_registry.close()
    return CheckResult("world_index_cache", True, "world.index registered with CacheRegistry")


def _flatten_json_keys(value: object, prefix: str = "") -> set[str]:
    """展开嵌套翻译字典的叶子键。"""
    if not isinstance(value, dict):
        return {prefix} if prefix else set()
    keys: set[str] = set()
    for key, child in value.items():
        child_prefix = f"{prefix}.{key}" if prefix else str(key)
        keys.update(_flatten_json_keys(child, child_prefix))
    return keys


def check_translation_parity() -> CheckResult:
    """确认中英文权威 UI 词典保持键集合一致。"""
    translation_root = PROJECT_ROOT / "translations"
    try:
        zh = json.loads(
            (translation_root / "zh_CN.json").read_text(encoding="utf-8-sig")
        )
        en = json.loads(
            (translation_root / "en_US.json").read_text(encoding="utf-8-sig")
        )
    except (OSError, json.JSONDecodeError) as exc:
        return CheckResult("translation_parity", False, str(exc))
    zh_keys = _flatten_json_keys(zh)
    en_keys = _flatten_json_keys(en)
    if zh_keys != en_keys:
        missing_en = sorted(zh_keys - en_keys)[:5]
        missing_zh = sorted(en_keys - zh_keys)[:5]
        return CheckResult(
            "translation_parity",
            False,
            f"missing_en={missing_en}; missing_zh={missing_zh}",
        )
    return CheckResult("translation_parity", True, f"{len(zh_keys)} keys aligned")


def _run_command(
    name: str,
    command: list[str],
    *,
    timeout_seconds: int,
) -> CheckResult:
    """执行一个有硬超时的质量门禁并返回最后一行。"""
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
            env={**os.environ, "PYTEST_ADDOPTS": ""},
        )
    except subprocess.TimeoutExpired:
        return CheckResult(name, False, f"timeout>{timeout_seconds}s")
    except OSError as exc:
        return CheckResult(name, False, str(exc))
    output = (completed.stdout or "") + (completed.stderr or "")
    detail = output.strip().splitlines()[-1] if output.strip() else f"exit={completed.returncode}"
    return CheckResult(name, completed.returncode == 0, detail)


def run_pytest() -> CheckResult:
    return _run_command(
        "pytest",
        [sys.executable, "-m", "pytest", "-q", "tests"],
        timeout_seconds=180,
    )


def run_benchmark() -> CheckResult:
    command = [sys.executable, "-m", "scripts.bench_architecture"]
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except subprocess.TimeoutExpired:
        return CheckResult("benchmark", False, "timeout>20s")
    except OSError as exc:
        return CheckResult("benchmark", False, str(exc))
    if completed.returncode != 0:
        return CheckResult("benchmark", False, (completed.stderr or completed.stdout).strip())
    try:
        payload = json.loads(completed.stdout.strip())
    except json.JSONDecodeError as exc:
        return CheckResult("benchmark", False, f"invalid json: {exc}")
    runtime = payload.get("runtime", {})
    cache = payload.get("cache", {})
    writes = payload.get("world_writes", {})
    world_index = payload.get("world_index", {})
    ok = (
        runtime.get("cpu_workers", 99) <= runtime.get("cpu_worker_limit", 0)
        and runtime.get("queue_rejected") is True
        and runtime.get("active_after_cancel") == 0
        and runtime.get("cancel_latency_ms", 9999) < 500
        and cache.get("used_bytes", 0) <= cache.get("budget_bytes", -1)
        and cache.get("evictions", 0) >= 1
        and cache.get("overcommit_rejected") is True
        and writes.get("same_world_blocked") is True
        and writes.get("different_world_allowed") is True
        and world_index.get("samples", 0) >= 5
        and world_index.get("warm_median_ms", 9999)
        <= world_index.get("cold_ms", 0) * 1.5
    )
    return CheckResult("benchmark", ok, json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _mca_sample_metrics(
    payload: dict[str, object],
) -> tuple[set[str], list[str]]:
    """验证 MCA 基准样本覆盖与缓存命中字段。"""
    samples = payload.get("samples")
    if not isinstance(samples, list):
        return set(), ["samples missing"]
    sample_sizes = {
        str(item.get("size"))
        for item in samples
        if isinstance(item, dict)
    }
    errors: list[str] = []
    if sample_sizes != {"small", "medium", "large"}:
        errors.append(f"sample sizes incomplete: {sorted(sample_sizes)}")
    for item in samples:
        if not isinstance(item, dict):
            errors.append("sample is not an object")
            continue
        size = str(item.get("size", "?"))
        topview = item.get("topview")
        if not isinstance(topview, dict):
            errors.append(f"{size}: topview missing")
            continue
        hit_p95 = topview.get("cache_hit_p95_ms")
        hit_count = topview.get("cache_hit_count")
        if not isinstance(hit_p95, (int, float)):
            errors.append(f"{size}: cache hit p95 missing")
        if not isinstance(hit_count, int) or hit_count < 1:
            errors.append(f"{size}: cache hit sample missing")
    return sample_sizes, errors


def _mca_budget_is_ok(payload: dict[str, object]) -> bool:
    """确认基准命令执行并返回了无违规预算结果。"""
    budget_result = payload.get("budget_result")
    violations = payload.get("budget_violations")
    return (
        payload.get("budgets_ok") is True
        and isinstance(budget_result, dict)
        and budget_result.get("ok") is True
        and budget_result.get("checked_samples") == 3
        and budget_result.get("violations") == []
        and isinstance(violations, list)
        and not violations
    )


def run_mca_benchmark() -> CheckResult:
    """运行 MCA/世界路径基准并消费合成 p95 预算结果。"""
    command = [
        sys.executable,
        "-m",
        "scripts.bench_mca",
        "--sizes",
        "small",
        "medium",
        "large",
        "--loops",
        "3",
        "--check-budgets",
        "--json",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return CheckResult("mca_benchmark", False, "timeout>60s")
    except OSError as exc:
        return CheckResult("mca_benchmark", False, str(exc))

    output = (completed.stdout or "").strip()
    if not output:
        detail = (completed.stderr or "").strip()
        return CheckResult(
            "mca_benchmark",
            False,
            detail or f"exit={completed.returncode}",
        )
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        return CheckResult("mca_benchmark", False, f"invalid json: {exc}")
    if not isinstance(payload, dict):
        return CheckResult("mca_benchmark", False, "benchmark payload is not an object")

    sample_sizes, metric_errors = _mca_sample_metrics(payload)
    budget_result = payload.get("budget_result")
    violations = payload.get("budget_violations")
    budget_ok = _mca_budget_is_ok(payload)
    ok = completed.returncode == 0 and budget_ok and not metric_errors
    detail_payload = {
        "returncode": completed.returncode,
        "budget_result": budget_result,
        "budget_violations": violations,
        "metric_errors": metric_errors,
        "sample_sizes": sorted(sample_sizes),
    }
    return CheckResult(
        "mca_benchmark",
        ok,
        json.dumps(detail_payload, ensure_ascii=False, sort_keys=True),
    )


def run_all() -> list[CheckResult]:
    static_checks = [
        check_dependency_direction(),
        check_app_threadpools(),
        check_no_private_execution_runtime_fallback(),
        check_region_delete_uses_transaction(),
        check_views_use_feature_context(),
        check_core_threadpool_bounds(),
        check_forbidden_runtime_dependencies(),
        check_region_map_package(),
        check_world_index_cache(),
        check_translation_parity(),
    ]
    quality_checks = [
        _run_command(
            "flake8",
            ["flake8", "app", "core", "tests", "scripts", "build_nuitka.py", "main.py"],
            timeout_seconds=90,
        ),
        _run_command(
            "mypy",
            [
                "mypy",
                "app",
                "core",
                "tests",
                "scripts",
                "build_nuitka.py",
                "main.py",
            ],
            timeout_seconds=120,
        ),
        _run_command("pyright", ["pyright"], timeout_seconds=120),
        _run_command(
            "compileall",
            [
                sys.executable,
                "-m",
                "compileall",
                "-q",
                "app",
                "core",
                "tests",
                "scripts",
                "build_nuitka.py",
                "main.py",
            ],
            timeout_seconds=60,
        ),
        _run_command(
            "git_diff_check",
            ["git", "diff", "--check"],
            timeout_seconds=30,
        ),
    ]
    return [
        *static_checks,
        *quality_checks,
        run_benchmark(),
        run_mca_benchmark(),
        run_pytest(),
    ]


def main() -> int:
    results = run_all()
    report = {
        "ok": all(item.ok for item in results),
        "checks": [asdict(item) for item in results],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
