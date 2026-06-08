import shutil
from pathlib import Path
from typing import Dict, List, Optional

from .cleaner import clean_world
from .pure_cleaner import purge_mod_blocks_and_entities
from .uuid_utils import get_offline_uuid_str, load_usercache, get_online_uuid, get_name_from_uuid
from .utils import safe_destination_world, update_server_properties, replace_directory_tree
from .types import LogCallback


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
    """执行快速模式迁移

    Args:
        src_world: 源世界路径
        dest_dir: 目标目录
        world_name: 世界名称
        offline_mode: 是否离线模式
        do_clean: 是否清理
        pure_clean: 是否进行纯净扫描（移除模组方块/实体）
        manual_names: 手动玩家名列表
        log: 日志回调函数
    """
    dest_world = safe_destination_world(src_world, dest_dir, world_name)

    # 1. 准备目标目录
    if dest_world.exists():
        log("目标文件夹已存在，正在安全替换...", "WARN")
    log(f"正在复制存档到 {dest_world}", "FILE")
    replace_directory_tree(src_world, dest_world)

    # 2. 加载缓存（仅作辅助）
    cache = load_usercache(src_world)
    log(f"从 usercache 加载了 {len(cache)} 条记录", "CACHE")

    # 3. 确定要处理的玩家名列表
    names_to_process = set()
    templates_by_name: Dict[str, Path] = {}

    # 如果用户手动输入了名字，直接使用（优先级最高）
    if manual_names:
        names_to_process.update(manual_names)
        log(f"使用手动输入的玩家名: {', '.join(manual_names)}", "MANUAL")

    # 扫描 playerdata 目录，尝试识别其他玩家
    pd = dest_world / "playerdata"
    if pd.exists():
        files = list(pd.glob("*.dat"))
        for f in files:
            uuid_old = f.stem
            name = cache.get(uuid_old)
            if not name and not offline_mode:
                name = get_name_from_uuid(uuid_old, log)
            if name:
                names_to_process.add(name)
                templates_by_name.setdefault(name, f)
            else:
                log(f"无法识别 UUID: {uuid_old}，如果这是您的账号，请在手动输入框中填写玩家名", "WARN")

    # 4. 为每个玩家名生成双副本
    dual_count = 0
    if names_to_process:
        for name in names_to_process:
            offline_uuid = get_offline_uuid_str(name)
            online_uuid = None
            if not offline_mode:
                online_uuid, official_name = get_online_uuid(name, log)
                if official_name and official_name != name and name in templates_by_name:
                    templates_by_name.setdefault(
                        official_name, templates_by_name[name])

            # 确保 playerdata 目录存在
            pd.mkdir(exist_ok=True)

            # 生成离线副本（如果还没有）
            offline_file = pd / f"{offline_uuid}.dat"
            if not offline_file.exists():
                template_file = templates_by_name.get(name)
                if template_file:
                    shutil.copy2(template_file, offline_file)
                    dual_count += 1
                    log(f"生成离线副本: {offline_uuid}.dat (玩家 {name})", "INFO")
                else:
                    log(f"警告: playerdata 目录为空，无法为 {name} 创建离线副本", "WARN")

            # 生成正版副本（如果获取到了正版UUID）
            if online_uuid:
                online_file = pd / f"{online_uuid}.dat"
                if not online_file.exists():
                    template_file = templates_by_name.get(name)
                    if template_file:
                        shutil.copy2(template_file, online_file)
                        dual_count += 1
                        log(f"生成正版副本: {online_uuid}.dat (玩家 {name})", "INFO")
        log(f"共生成 {dual_count} 个双UUID副本", "INFO")
    else:
        log("未找到任何玩家数据，跳过双UUID生成", "WARN")

    # 5. 精简存档
    if do_clean:
        log("正在精简存档...", "CLEAN")
        clean_world(dest_world, log)
    else:
        log("跳过精简步骤", "INFO")

    # 6. 纯净扫描
    if pure_clean:
        log("正在执行纯净扫描：移除模组方块和实体...", "PURE")
        purge_mod_blocks_and_entities(dest_world, log)
    else:
        log("跳过纯净扫描", "INFO")

    # 7. 修改 server.properties
    update_server_properties(dest_dir, world_name, log)
