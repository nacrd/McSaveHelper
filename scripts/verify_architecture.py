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
    """应用服务层禁止再直接创建 ThreadPoolExecutor。"""
    offenders: list[str] = []
    allowed = {
        "app/services/execution_runtime.py",
        "app/services/runtime_map.py",
        "app/services/world_index_service.py",
        "app/services/region_map/meta.py",
    }
    for path in _iter_py_files(APP_ROOT / "services"):
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        source = path.read_text(encoding="utf-8-sig")
        if "ThreadPoolExecutor" in source and rel not in allowed:
            offenders.append(rel)
    if offenders:
        return CheckResult("app_threadpools", False, ", ".join(offenders))
    return CheckResult("app_threadpools", True, "no direct ThreadPoolExecutor in services")


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
        from app.services.region_map import RegionMapService

        service = RegionMapService()
        service.close()
    except (ImportError, RuntimeError, ValueError, OSError) as exc:
        return CheckResult("region_map_package", False, f"import/lifecycle: {exc}")
    return CheckResult("region_map_package", True, "scan/meta/topview package present")


def check_world_index_cache() -> CheckResult:
    from app.services.cache_registry import CacheRegistry
    from app.services.world_index_service import WorldIndexRegistry

    cache_registry = CacheRegistry(budget_bytes=4 * 1024 * 1024)
    world_indexes = None
    try:
        world_indexes = WorldIndexRegistry(
            max_entries=2,
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


def run_all() -> list[CheckResult]:
    static_checks = [
        check_dependency_direction(),
        check_app_threadpools(),
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
