"""分块复制的取消检查点回归测试。"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.cancellable_copy import (
    COPY_BUFFER_SIZE,
    CopyCancelledError,
    copy_tree_with_checkpoints,
)


def test_copy_tree_checks_cancellation_between_file_blocks(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    (source / "large.bin").write_bytes(b"x" * (COPY_BUFFER_SIZE * 2))
    checks = 0

    def cancel_after_first_block() -> None:
        nonlocal checks
        checks += 1
        if checks >= 2:
            raise CopyCancelledError("cancelled")

    with pytest.raises(CopyCancelledError):
        copy_tree_with_checkpoints(
            source,
            destination,
            cancel_after_first_block,
        )

    assert checks >= 2
    assert not (destination / "large.bin").exists() or (
        destination / "large.bin"
    ).stat().st_size < COPY_BUFFER_SIZE * 2
