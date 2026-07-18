from pathlib import Path

import pytest

import build_nuitka


def test_build_commands_cover_both_distribution_modes(tmp_path: Path) -> None:
    onefile = build_nuitka.build_command("onefile", tmp_path)
    portable = build_nuitka.build_command("portable", tmp_path)

    assert "--onefile" in onefile
    assert "--standalone" in portable
    assert "--zig" in onefile
    assert "--windows-console-mode=disable" in onefile
    assert "--enable-plugins=tk-inter" in onefile
    assert any(arg.startswith("--include-data-dir=") for arg in onefile)
    assert any(arg.startswith("--windows-icon-from-ico=") for arg in onefile)


def test_generated_cleanup_rejects_paths_outside_project(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="项目目录之外"):
        build_nuitka._remove_generated(tmp_path)


def test_repository_no_longer_references_pyinstaller() -> None:
    checked_files = (
        build_nuitka.PROJECT_ROOT / ".github/workflows/build.yml",
        build_nuitka.PROJECT_ROOT / "README.md",
        build_nuitka.PROJECT_ROOT / "AGENTS.md",
        build_nuitka.PROJECT_ROOT / "CLAUDE.md",
    )

    for path in checked_files:
        assert "pyinstaller" not in path.read_text(encoding="utf-8").lower()
