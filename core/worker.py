from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional, Callable, Tuple

from .nbt_utils import patch_nbt
from .types import UUIDMapping, LogCallback


def process_region_file(
    file_path: Path,
    mappings: List[UUIDMapping]
) -> Tuple[str, int, Optional[str]]:
    """处理单个 .mca 文件，返回 (文件路径, 修改次数, 错误信息)

    Args:
        file_path: 区域文件路径
        mappings: UUID 映射列表

    Returns:
        (文件路径, 修改次数, 错误信息)
    """
    try:
        from core.mca import WritableRegion
        region = WritableRegion.open(file_path)
        changes = 0
        for x, z, data in region.iter_chunks():
            if data:
                _, c = patch_nbt(data, mappings)
                changes += c
        if changes > 0:
            region.save(file_path, backup=True)
        return str(file_path), changes, None
    except Exception as e:
        return str(file_path), -1, str(e)


def dummy_progress(value: float) -> None:
    """虚拟进度函数，用于批量处理

    Args:
        value: 进度值 (0.0 - 1.0)
    """


def process_regions_parallel(
    files: List[Path],
    mappings: List[UUIDMapping],
    progress_callback: Callable[[float], None],
    log_callback: LogCallback
) -> int:
    """使用线程池并发处理区域文件

    Args:
        files: 区域文件列表
        mappings: UUID 映射列表
        progress_callback: 进度回调函数
        log_callback: 日志回调函数
    """
    total = len(files)
    done = 0
    total_changes = 0

    if total == 0:
        progress_callback(1.0)
        log_callback("区块总计修改: 0 处", "INFO")
        return 0

    errors: List[str] = []

    with ThreadPoolExecutor(max_workers=min(8, total)) as executor:
        futures = [
            executor.submit(
                process_region_file,
                f,
                mappings) for f in files]
        for future in as_completed(futures):
            path, changes, error = future.result()
            done += 1
            progress_callback(done / total)
            if changes > 0:
                total_changes += changes
                log_callback(f"MCA {Path(path).name}: 修改 {changes} 处", "INFO")
            elif changes == -1:
                err_msg = f"处理失败: {error}" if error else "未知错误"
                log_callback(f"MCA {Path(path).name}: {err_msg}", "ERROR")
                errors.append(f"{path}: {err_msg}")
    if errors:
        raise RuntimeError(f"{len(errors)} 个区域文件处理失败: {errors[0]}")
    log_callback(f"区块总计修改: {total_changes} 处", "INFO")
    return total_changes
