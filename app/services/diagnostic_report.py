"""诊断报告文件写入服务。"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def write_diagnostic_report(path: Path | str, content: str) -> Path:
    """以原子方式写入诊断报告文本。

    Args:
        path: 用户选择的报告目标路径。
        content: 已格式化的报告正文。

    Returns:
        规范化后的报告路径。

    Raises:
        OSError: 目标目录不可用或替换失败。
    """
    target = Path(path).expanduser().resolve()
    if not target.parent.is_dir():
        raise FileNotFoundError(f"诊断报告目录不存在: {target.parent}")

    temporary_path: Path | None = None
    try:
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
            text=True,
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, target)
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
    return target


__all__ = ["write_diagnostic_report"]
