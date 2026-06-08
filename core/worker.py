from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional, Callable, Tuple

import nbtlib
import anvil

from .nbt_utils import patch_nbt
from .types import UUIDMapping, LogCallback, ProgressCallback


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
        region = anvil.Region.from_file(str(file_path))   # 修正1：使用 anvil.Region
        changes = 0
        for x in range(32):
            for z in range(32):
                chunk = region.get_chunk(x, z)
                if chunk:
                    data = chunk if isinstance(
                        chunk, nbtlib.tag.Compound) else chunk.data
                    if data:
                        _, c = patch_nbt(data, mappings)
                        changes += c
        if changes > 0:
            region.save(str(file_path))  # type: ignore[attr-defined]
        return str(file_path), changes, None
    except Exception as e:
        return str(file_path), -1, str(e)


def dummy_progress(value: float) -> None:
    """虚拟进度函数，用于批量处理

    Args:
        value: 进度值 (0.0 - 1.0)
    """
    pass


def process_regions_parallel(
    files: List[Path],
    mappings: List[UUIDMapping],
    progress_callback: Callable[[float], None],
    log_callback: LogCallback
) -> None:
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
        return

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
    log_callback(f"区块总计修改: {total_changes} 处", "INFO")
