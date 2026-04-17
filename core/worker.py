from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import nbtlib
from anvil import Region

from .nbt_utils import patch_nbt


def process_region_file(file_path, mappings):
    """处理单个 .mca 文件，返回 (文件路径, 修改次数)"""
    try:
        region = Region.from_file(str(file_path))
        changes = 0
        for x in range(32):
            for z in range(32):
                chunk = region.get_chunk(x, z)
                if chunk:
                    data = chunk if isinstance(chunk, nbtlib.tag.Compound) else chunk.data
                    if data:
                        _, c = patch_nbt(data, mappings)
                        changes += c
        if changes > 0:
            region.save(str(file_path))
        return str(file_path), changes, None
    except Exception as e:
        return str(file_path), -1, str(e)

def process_regions_parallel(files, mappings, progress_callback, log_callback):
    """使用线程池并发处理区域文件"""
    total = len(files)
    done = 0
    total_changes = 0

    # 使用 ThreadPoolExecutor 代替 ProcessPoolExecutor
    with ThreadPoolExecutor(max_workers=min(8, total)) as executor:
        futures = [executor.submit(process_region_file, f, mappings) for f in files]
        for future in as_completed(futures):
            path, changes, error = future.result()
            done += 1
            progress_callback(done / total)
            if changes > 0:
                total_changes += changes
                log_callback(f"MCA {Path(path).name}: 修改 {changes} 处")
            elif changes == -1:
                # 输出具体错误原因
                err_msg = f"处理失败: {error}" if error else "未知错误"
                log_callback(f"MCA {Path(path).name}: {err_msg}", "ERROR")
    log_callback(f"区块总计修改: {total_changes} 处", "INFO")