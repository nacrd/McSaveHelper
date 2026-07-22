"""Concurrent MCA UUID patching helpers for full-mode migration."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from .nbt_utils import patch_nbt
from .parallel import clamp_workers
from .types import LogCallback, UUIDMapping


def process_region_file(
    file_path: Path,
    mappings: List[UUIDMapping],
) -> Tuple[str, int, Optional[str]]:
    """处理单个 ``.mca`` 文件。

    Args:
        file_path: 区域文件路径。
        mappings: UUID 映射列表。

    Returns:
        tuple: ``(文件路径, 修改次数, 错误信息)``；失败时修改次数为 ``-1``。
    """
    try:
        from core.mca import WritableRegion

        region = WritableRegion.open(file_path)
        changes = 0
        for _x, _z, data in region.iter_chunks():
            if data:
                _, count = patch_nbt(data, mappings)
                changes += count
        if changes > 0:
            region.save(file_path, backup=True)
        return str(file_path), changes, None
    except (OSError, ValueError, TypeError, RuntimeError, KeyError) as exc:
        return str(file_path), -1, str(exc)
    except Exception as exc:
        # Worker boundary: one bad region must not kill the pool.
        return str(file_path), -1, str(exc)


def dummy_progress(value: float) -> None:
    """No-op progress callback for batch callers.

    Args:
        value: Progress fraction in ``[0.0, 1.0]``.
    """
    del value


def process_regions_parallel(
    files: List[Path],
    mappings: List[UUIDMapping],
    progress_callback: Callable[[float], None],
    log_callback: LogCallback,
    max_workers: Optional[int] = None,
) -> int:
    """使用线程池并发处理区域文件。

    Args:
        files: 区域文件列表。
        mappings: UUID 映射列表。
        progress_callback: 进度回调 ``(0..1)``。
        log_callback: 日志回调。
        max_workers: 可选区域级并发上限；批量世界任务应传 1，避免嵌套扩张。

    Returns:
        int: 所有区域的修改总次数。

    Raises:
        RuntimeError: 至少一个区域处理失败时。
    """
    total = len(files)
    done = 0
    total_changes = 0

    if total == 0:
        progress_callback(1.0)
        log_callback("区块总计修改: 0 处", "INFO")
        return 0

    errors: List[str] = []
    workers = clamp_workers(max_workers, item_count=total)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(process_region_file, region_path, mappings)
            for region_path in files
        ]
        for future in as_completed(futures):
            path, changes, error = future.result()
            done += 1
            progress_callback(done / total)
            if changes > 0:
                total_changes += changes
                log_callback(
                    f"MCA {Path(path).name}: 修改 {changes} 处",
                    "INFO",
                )
            elif changes == -1:
                err_msg = f"处理失败: {error}" if error else "未知错误"
                log_callback(f"MCA {Path(path).name}: {err_msg}", "ERROR")
                errors.append(f"{path}: {err_msg}")
    if errors:
        raise RuntimeError(
            f"{len(errors)} 个区域文件处理失败: {errors[0]}"
        )
    log_callback(f"区块总计修改: {total_changes} 处", "INFO")
    return total_changes
