"""带协作检查点的文件复制基础能力。"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable, Optional


COPY_BUFFER_SIZE = 1024 * 1024
Checkpoint = Callable[[], None]


class CopyCancelledError(RuntimeError):
    """目录复制在安全检查点收到取消请求。"""


def copy_file_with_checkpoints(
    source: Path,
    destination: Path,
    checkpoint: Checkpoint,
) -> int:
    """分块复制一个普通文件，并在每个块边界执行检查点。

    Args:
        source: 要复制的源文件。
        destination: 位于调用方暂存目录中的目标文件。
        checkpoint: 可抛出取消或领域异常的无参回调。

    Returns:
        实际复制的字节数。
    """
    copied = 0
    checkpoint()
    with source.open("rb") as source_file, destination.open("wb") as target_file:
        while True:
            block = source_file.read(COPY_BUFFER_SIZE)
            if not block:
                break
            target_file.write(block)
            copied += len(block)
            checkpoint()
    shutil.copystat(source, destination, follow_symlinks=False)
    return copied


def copy_tree_with_checkpoints(
    source: Path,
    destination: Path,
    checkpoint: Checkpoint,
    *,
    ignore: Optional[Callable[[str, list[str]], set[str]]] = None,
) -> int:
    """复制目录树，并把每个文件交给分块复制检查点。

    ``shutil.copytree`` 仍负责目录创建、忽略规则和确定性遍历；文件
    内容通过 :func:`copy_file_with_checkpoints` 写入，因此取消不会等到
    整个世界复制完才生效。

    Args:
        source: 源目录。
        destination: 新的暂存目录。
        checkpoint: 每个块前后执行的协作检查点。
        ignore: 与 ``shutil.copytree`` 相同的忽略回调。

    Returns:
        已复制的文件字节数（近似值）。
    """
    copied_bytes = 0

    def copy_file(source_name: str, destination_name: str) -> str:
        nonlocal copied_bytes
        copied_bytes += copy_file_with_checkpoints(
            Path(source_name),
            Path(destination_name),
            checkpoint,
        )
        return destination_name

    checkpoint()
    shutil.copytree(
        source,
        destination,
        ignore=ignore,
        copy_function=copy_file,
    )
    checkpoint()
    return copied_bytes


__all__ = [
    "COPY_BUFFER_SIZE",
    "CopyCancelledError",
    "copy_file_with_checkpoints",
    "copy_tree_with_checkpoints",
]
