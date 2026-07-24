"""诊断报告原子写入测试。"""
from pathlib import Path

import pytest

from app.services.diagnostic_report import write_diagnostic_report


def test_write_diagnostic_report_replaces_target_atomically(tmp_path: Path) -> None:
    target = tmp_path / "diagnostics.txt"
    target.write_text("old", encoding="utf-8")

    result = write_diagnostic_report(target, "new\n")

    assert result == target.resolve()
    assert target.read_text(encoding="utf-8") == "new\n"
    assert list(tmp_path.glob(".diagnostics.txt.*.tmp")) == []


def test_write_diagnostic_report_rejects_missing_parent(tmp_path: Path) -> None:
    target = tmp_path / "missing" / "diagnostics.txt"

    with pytest.raises(FileNotFoundError, match="诊断报告目录不存在"):
        write_diagnostic_report(target, "content")
