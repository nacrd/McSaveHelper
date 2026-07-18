"""Build MCSaveHelper Windows artifacts with Nuitka."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Literal, Sequence


BuildMode = Literal["onefile", "portable"]

PROJECT_ROOT = Path(__file__).resolve().parent
ENTRYPOINT = PROJECT_ROOT / "main.py"
ICON_PATH = PROJECT_ROOT / "mcsavehelper_icon.ico"
TRANSLATIONS_DIR = PROJECT_ROOT / "translations"
BUILD_ROOT = PROJECT_ROOT / "build"
DIST_ROOT = PROJECT_ROOT / "dist"


def build_command(mode: BuildMode, output_dir: Path) -> list[str]:
    """Return the reproducible Nuitka command for a build mode."""
    mode_option = "--onefile" if mode == "onefile" else "--standalone"
    return [
        sys.executable,
        "-m",
        "nuitka",
        mode_option,
        "--assume-yes-for-downloads",
        "--zig",
        "--windows-console-mode=disable",
        f"--windows-icon-from-ico={ICON_PATH}",
        "--enable-plugins=tk-inter",
        "--include-package=app",
        "--include-package=core",
        "--include-package=flet",
        "--include-package=flet_desktop",
        "--include-package=nbtlib",
        "--include-package-data=flet",
        "--include-package-data=flet_desktop",
        "--include-distribution-metadata=flet",
        "--include-distribution-metadata=flet-desktop",
        f"--include-data-dir={TRANSLATIONS_DIR}=translations",
        f"--include-data-files={ICON_PATH}=mcsavehelper_icon.ico",
        f"--output-dir={output_dir}",
        "--output-filename=MCSaveHelper.exe",
        str(ENTRYPOINT),
    ]


def _remove_generated(path: Path) -> None:
    """Remove one generated path after proving it belongs to the project."""
    resolved = path.resolve()
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise RuntimeError(f"拒绝清理项目目录之外的路径: {resolved}") from exc

    if resolved.is_dir():
        shutil.rmtree(resolved)
    elif resolved.exists():
        resolved.unlink()


def _validate_inputs() -> None:
    missing = [
        path
        for path in (ENTRYPOINT, ICON_PATH, TRANSLATIONS_DIR)
        if not path.exists()
    ]
    if missing:
        joined = ", ".join(str(path) for path in missing)
        raise FileNotFoundError(f"缺少构建输入: {joined}")


def _publish(mode: BuildMode, output_dir: Path) -> Path:
    DIST_ROOT.mkdir(parents=True, exist_ok=True)

    if mode == "onefile":
        source = output_dir / "MCSaveHelper.exe"
        target = DIST_ROOT / "MCSaveHelper.exe"
    else:
        source = output_dir / f"{ENTRYPOINT.stem}.dist"
        target = DIST_ROOT / "MCSaveHelper"

    if not source.exists():
        raise FileNotFoundError(f"Nuitka 未生成预期产物: {source}")

    _remove_generated(target)
    shutil.move(str(source), str(target))
    return target


def build(mode: BuildMode) -> Path:
    """Compile one artifact and publish it under ``dist``."""
    _validate_inputs()
    output_dir = BUILD_ROOT / f"nuitka-{mode}"
    _remove_generated(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        build_command(mode, output_dir),
        cwd=PROJECT_ROOT,
        check=True,
    )
    artifact = _publish(mode, output_dir)
    _remove_generated(output_dir)
    print(f"构建完成: {artifact}")
    return artifact


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="使用 Nuitka 构建 MCSaveHelper")
    parser.add_argument("mode", choices=("onefile", "portable"))
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    build(args.mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
