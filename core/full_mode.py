from pathlib import Path
from typing import Dict, List, Optional

import core.nbt as nbtlib

from .cleaner import clean_world
from .pure_cleaner import purge_mod_blocks_and_entities
from .nbt_utils import patch_nbt
from .scanner import scan_all_regions
from .uuid_utils import build_mappings, load_usercache
from .worker import process_regions_parallel
from .utils import (
    safe_destination_world, update_server_properties, replace_directory_tree,
    find_player_data_dirs, find_stats_dirs, find_advancements_dirs, find_data_dirs,
)
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
    progress: ProgressCallback,
    custom_mappings: Optional[Dict[str, str]] = None,
    region_workers: Optional[int] = None,
) -> None:
    """执行完整模式迁移。

    克隆世界后构建 UUID 映射，并行修补区域与玩家相关 NBT，并更新
    ``server.properties``。

    Args:
        src_world: 源世界路径。
        dest_dir: 目标输出父目录。
        world_name: 目标世界文件夹名。
        offline_mode: 是否离线模式。
        do_clean: 是否常规清理。
        pure_clean: 是否纯净清理。
        manual_names: 手动玩家名列表。
        log: 日志回调。
        progress: 进度回调 ``(0..1)`` 或带消息的实现。
        custom_mappings: 玩家名 → 自定义 UUID 覆盖。
        region_workers: 区域级并发上限；批量世界迁移应传 1。

    Raises:
        ValueError / OSError: 路径或 I/O 失败时由底层工具抛出。
    """
    dest_world = safe_destination_world(src_world, dest_dir, world_name)

    # 1. 克隆
    replace_directory_tree(src_world, dest_world)
    log(f"存档已克隆到 {dest_world}", "FILE")

    # 2. 加载缓存与构建映射
    mappings = _build_full_mode_mappings(
        src_world,
        dest_world,
        offline_mode,
        manual_names,
        log,
        custom_mappings,
    )
    _process_core_nbt(dest_world, mappings, log)
    _rename_player_files(dest_world, mappings, log)
    _process_regions(
        dest_world,
        mappings,
        progress,
        log,
        region_workers,
    )

    # 6. 精简
    if do_clean:
        clean_world(dest_world, log)

    _run_pure_clean(dest_world, pure_clean, log, region_workers)

    # 8. 修改 server.properties
    update_server_properties(dest_dir, world_name, log)


def _build_full_mode_mappings(
    src_world: Path,
    dest_world: Path,
    offline_mode: bool,
    manual_names: Optional[List[str]],
    log: LogCallback,
    custom_mappings: Optional[Dict[str, str]],
) -> List[UUIDMapping]:
    cache = load_usercache(src_world)
    log(f"本地缓存: {len(cache)} 条", "CACHE")
    mappings = build_mappings(
        dest_world,
        cache,
        offline_mode,
        manual_names,
        log,
        custom_mappings,
    )
    if not mappings:
        log("未生成任何 UUID 映射，终止", "ERROR")
        raise RuntimeError("未生成任何 UUID 映射，完整迁移已中止")
    log(f"生成 {len(mappings)} 条映射", "INFO")
    return mappings


def _process_core_nbt(
    dest_world: Path,
    mappings: List[UUIDMapping],
    log: LogCallback,
) -> None:
    log("处理核心 NBT 文件...", "NBT")
    level_changes = process_nbt_file(
        dest_world / "level.dat", mappings, log, required=True
    )
    log(f"level.dat 修改 {level_changes} 处", "INFO")
    for data_dir in find_data_dirs(dest_world):
        for data_file in data_dir.glob("*.dat"):
            process_nbt_file(data_file, mappings, log, required=True)


def _rename_player_files(
    dest_world: Path,
    mappings: List[UUIDMapping],
    log: LogCallback,
) -> None:
    log("重命名玩家文件...", "FILE")
    rename_folders: List[Path] = []
    for find_fn in (find_player_data_dirs, find_stats_dirs, find_advancements_dirs):
        rename_folders.extend(find_fn(dest_world))
    for folder in dict.fromkeys(rename_folders):
        if not folder.exists():
            continue
        for mapping in mappings:
            _rename_mapping_files(folder, mapping, log)


def _rename_mapping_files(
    folder: Path,
    mapping: UUIDMapping,
    log: LogCallback,
) -> None:
    old_uuid, new_uuid = mapping[2], mapping[3]
    for old_file in folder.glob(f"{old_uuid}*"):
        new_name = old_file.name.replace(old_uuid, new_uuid)
        new_path = folder / new_name
        if new_path.exists():
            log(
                f"跳过重命名冲突: {old_file.name} -> {new_name}，目标已存在",
                "WARN",
            )
            continue
        old_file.rename(new_path)


def _process_regions(
    dest_world: Path,
    mappings: List[UUIDMapping],
    progress: ProgressCallback,
    log: LogCallback,
    max_workers: Optional[int],
) -> None:
    log("扫描区域文件...", "MCA")
    mca_files = scan_all_regions(dest_world)
    log(f"发现 {len(mca_files)} 个 .mca 文件", "INFO")
    if mca_files:
        process_regions_parallel(
            mca_files,
            mappings,
            progress,
            log,
            max_workers=max_workers,
        )
    else:
        log("没有区域文件需要处理", "INFO")


def _run_pure_clean(
    dest_world: Path,
    enabled: bool,
    log: LogCallback,
    max_workers: Optional[int],
) -> None:
    if not enabled:
        log("跳过纯净扫描", "INFO")
        return
    log("正在执行纯净扫描：移除模组方块和实体...", "PURE")
    if not purge_mod_blocks_and_entities(
        dest_world,
        log,
        max_workers=max_workers,
    ):
        raise RuntimeError("纯净扫描未完整处理所有区域文件")


def process_nbt_file(
    path: Path,
    mappings: List[UUIDMapping],
    log: LogCallback,
    required: bool = False,
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
            nbtlib.save(tag, path)
        return c
    except Exception as e:
        log(f"处理失败 {path.name}: {e}", "ERROR")
        if required:
            raise RuntimeError(f"必要 NBT 文件处理失败: {path}") from e
        return 0
