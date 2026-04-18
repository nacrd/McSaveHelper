import shutil
from pathlib import Path
from typing import List, Optional

import nbtlib

from .cleaner import clean_world
from .pure_cleaner import purge_mod_blocks_and_entities
from .nbt_utils import patch_nbt
from .scanner import scan_all_regions
from .uuid_utils import build_mappings, load_usercache
from .worker import process_regions_parallel
from .utils import update_server_properties
from .types import LogCallback, ProgressCallback, UUIDMapping


def run_full(
    src_world: Path,
    dest_dir: Path,
    world_name: str,
    offline_mode: bool,
    do_clean: bool,
    pure_clean: bool,
    manual_names: Optional[List[str]],
    log: LogCallback,
    progress: ProgressCallback
) -> None:
    """执行完整模式迁移

    Args:
        src_world: 源世界路径
        dest_dir: 目标目录
        world_name: 世界名称
        offline_mode: 是否离线模式
        do_clean: 是否清理
        pure_clean: 是否进行纯净扫描（移除模组方块/实体）
        manual_names: 手动玩家名列表
        log: 日志回调函数
        progress: 进度回调函数
    """
    dest_world = dest_dir / world_name

    # 1. 克隆
    if dest_world.exists():
        shutil.rmtree(dest_world)
    shutil.copytree(src_world, dest_world)
    log(f"存档已克隆到 {dest_world}", "FILE")

    # 2. 加载缓存与构建映射
    cache = load_usercache(src_world)
    log(f"本地缓存: {len(cache)} 条", "CACHE")
    mappings = build_mappings(dest_world, cache, offline_mode, manual_names, log)
    if not mappings:
        log("未生成任何 UUID 映射，终止", "ERROR")
        return
    log(f"生成 {len(mappings)} 条映射", "INFO")

    # 3. 处理核心 NBT 文件
    log("处理核心 NBT 文件...", "NBT")
    l_c = process_nbt_file(dest_world / "level.dat", mappings, log)
    log(f"level.dat 修改 {l_c} 处", "INFO")

    data_dir = dest_world / "data"
    if data_dir.exists():
        for df in data_dir.glob("*.dat"):
            process_nbt_file(df, mappings, log)

    # 4. 物理重命名
    log("重命名玩家文件...", "FILE")
    for folder in ["playerdata", "stats", "advancements"]:
        f_path = dest_world / folder
        if f_path.exists():
            for m in mappings:
                old_u, new_u = m[2], m[3]
                for old_file in f_path.glob(f"{old_u}*"):
                    new_name = old_file.name.replace(old_u, new_u)
                    new_path = f_path / new_name
                    if new_path.exists():
                        new_path.unlink(missing_ok=True)
                    old_file.rename(new_path)

    # 5. 处理区域文件
    log("扫描区域文件...", "MCA")
    mca_files = scan_all_regions(dest_world)
    total = len(mca_files)
    log(f"发现 {total} 个 .mca 文件", "INFO")
    if total > 0:
        process_regions_parallel(mca_files, mappings, progress, log)
    else:
        log("没有区域文件需要处理", "INFO")

    # 6. 精简
    if do_clean:
        clean_world(dest_world, log)

    # 7. 纯净扫描
    if pure_clean:
        log("正在执行纯净扫描：移除模组方块和实体...", "PURE")
        purge_mod_blocks_and_entities(dest_world, log)
    else:
        log("跳过纯净扫描", "INFO")

    # 8. 修改 server.properties
    update_server_properties(dest_dir, world_name, log)


def process_nbt_file(
    path: Path,
    mappings: List[UUIDMapping],
    log: LogCallback
) -> int:
    """处理单个 NBT 文件

    Args:
        path: NBT 文件路径
        mappings: UUID 映射列表
        log: 日志回调函数

    Returns:
        修改次数
    """
    try:
        tag = nbtlib.load(path)
        _, c = patch_nbt(tag, mappings)
        if c > 0:
            nbtlib.save(tag, path)  # type: ignore[attr-defined]
        return c
    except Exception as e:
        log(f"处理失败 {path.name}: {e}", "ERROR")
        return 0
