import shutil
from pathlib import Path
from typing import Dict, List, Optional

from .cleaner import clean_world
from .pure_cleaner import purge_mod_blocks_and_entities
from .uuid_utils import get_offline_uuid_str, load_usercache, get_online_uuid, get_name_from_uuid
from .utils import (
    safe_destination_world, update_server_properties, replace_directory_tree,
    get_write_player_data_dir, list_player_dat_files,
)
from .types import LogCallback


def _collect_player_names(
    world_path: Path,
    cache: Dict[str, str],
    offline_mode: bool,
    manual_names: Optional[List[str]],
    log: LogCallback,
) -> tuple[set[str], Dict[str, Path]]:
    names: set[str] = set()
    templates: Dict[str, Path] = {}
    unresolved: List[Path] = []
    for player_file in list_player_dat_files(world_path):
        old_uuid = player_file.stem
        name = cache.get(old_uuid)
        if not name and not offline_mode:
            name = get_name_from_uuid(old_uuid, log)
        if name:
            names.add(name)
            templates.setdefault(name, player_file)
        else:
            unresolved.append(player_file)
            log(
                f"无法识别 UUID: {old_uuid}，如果这是您的账号，请在手动输入框中填写玩家名",
                "WARN",
            )
    if manual_names:
        names_list = [name.strip() for name in manual_names if name.strip()]
        if len(names_list) != len(unresolved) or len(set(names_list)) != len(names_list):
            raise ValueError(
                f"未知玩家数量为 {len(unresolved)}，手动名称数量为 {len(names_list)}，"
                "必须一对一且名称不能重复"
            )
        for player_file, name in zip(sorted(unresolved), names_list):
            names.add(name)
            templates[name] = player_file
            log(f"手动关联玩家: {player_file.stem} -> {name}", "MANUAL")
    return names, templates


def _copy_player_variant(
    player_dir: Path,
    name: str,
    uuid_value: Optional[str],
    templates: Dict[str, Path],
    log: LogCallback,
    label: str,
) -> bool:
    if not uuid_value:
        return False
    target = player_dir / f"{uuid_value}.dat"
    if target.exists():
        return False
    template = templates.get(name)
    if template is None:
        log(f"警告: 玩家数据目录为空，无法为 {name} 创建{label}副本", "WARN")
        return False
    shutil.copy2(template, target)
    log(f"生成{label}副本: {uuid_value}.dat (玩家 {name})", "INFO")
    return True


def _create_dual_player_files(
    world_path: Path,
    names: set[str],
    templates: Dict[str, Path],
    offline_mode: bool,
    log: LogCallback,
) -> None:
    if not names:
        log("未找到任何玩家数据，跳过双UUID生成", "WARN")
        return
    player_dir = get_write_player_data_dir(world_path)
    created = 0
    for name in names:
        offline_uuid = get_offline_uuid_str(name)
        online_uuid: Optional[str] = None
        if not offline_mode:
            online_uuid, official_name = get_online_uuid(name, log)
            if official_name and official_name != name:
                template = templates.get(name)
                if template is not None:
                    templates.setdefault(official_name, template)
        player_dir.mkdir(exist_ok=True, parents=True)
        if _copy_player_variant(
                player_dir, name, offline_uuid, templates, log, "离线"):
            created += 1
        if _copy_player_variant(
                player_dir, name, online_uuid, templates, log, "正版"):
            created += 1
    log(f"共生成 {created} 个双UUID副本", "INFO")


def run_fast(
    src_world: Path,
    dest_dir: Path,
    world_name: str,
    offline_mode: bool,
    do_clean: bool,
    pure_clean: bool,
    manual_names: Optional[List[str]],
    log: LogCallback
) -> None:
    """执行快速模式迁移。

    复制世界后按 usercache/手动名单生成双 UUID 玩家文件，可选清理。

    Args:
        src_world: 源世界路径。
        dest_dir: 目标输出父目录。
        world_name: 目标世界文件夹名。
        offline_mode: 是否以离线 UUID 为主生成副本。
        do_clean: 是否执行常规清理。
        pure_clean: 是否执行纯净清理（移除模组方块/实体）。
        manual_names: 额外手动玩家名列表。
        log: 日志回调。

    Raises:
        ValueError / OSError: 目标路径不安全或复制失败时由工具函数抛出。
    """
    dest_world = safe_destination_world(src_world, dest_dir, world_name)

    if dest_world.exists():
        log("目标文件夹已存在，正在安全替换...", "WARN")
    log(f"正在复制存档到 {dest_world}", "FILE")
    replace_directory_tree(src_world, dest_world)

    cache = load_usercache(src_world)
    log(f"从 usercache 加载了 {len(cache)} 条记录", "CACHE")
    names, templates = _collect_player_names(
        dest_world,
        cache,
        offline_mode,
        manual_names,
        log,
    )
    _create_dual_player_files(
        dest_world,
        names,
        templates,
        offline_mode,
        log,
    )
    _apply_fast_mode_cleanup(dest_world, do_clean, pure_clean, log)
    update_server_properties(dest_dir, world_name, log)


def _apply_fast_mode_cleanup(
    dest_world: Path,
    do_clean: bool,
    pure_clean: bool,
    log: LogCallback,
) -> None:
    if do_clean:
        log("正在精简存档...", "CLEAN")
        clean_world(dest_world, log)
    else:
        log("跳过精简步骤", "INFO")

    if pure_clean:
        log("正在执行纯净扫描：移除模组方块和实体...", "PURE")
        if not purge_mod_blocks_and_entities(dest_world, log):
            raise RuntimeError("纯净扫描未完整处理所有区域文件")
    else:
        log("跳过纯净扫描", "INFO")
