"""Qt 迁移树的架构边界测试。"""
from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_qtui_does_not_import_flet_tree() -> None:
    """Qt 代码不得反向依赖 Flet 包或 app.ui。"""
    offenders: list[str] = []
    qt_root = PROJECT_ROOT / "app" / "qtui"
    for path in qt_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported_modules: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.append(node.module)
        if any(
            module == "flet"
            or module.startswith("flet.")
            or module == "app.ui"
            or module.startswith("app.ui.")
            for module in imported_modules
        ):
            offenders.append(path.relative_to(PROJECT_ROOT).as_posix())

    assert offenders == []


def test_qt_registry_exposes_only_migrated_views(qt_app: object) -> None:
    """Qt 侧边栏包含已迁移页面。"""
    del qt_app
    from app.qtui.registry import create_qt_registry

    view_ids = [feature.view_id for feature in create_qt_registry().features]

    assert "migrator" in view_ids
    assert "server_properties" in view_ids
    assert view_ids[0] == "explorer"
