import shutil

from .cleaner import clean_world
from .uuid_utils import get_offline_uuid_str, load_usercache, get_online_uuid, get_name_from_uuid


def run_fast(src_world, dest_dir, world_name, offline_mode, do_clean, manual_names, log, progress):
    dest_world = dest_dir / world_name

    # 1. 准备目标目录
    if dest_world.exists():
        log("目标文件夹已存在，正在删除...", "WARN")
        shutil.rmtree(dest_world)
    log(f"正在复制存档到 {dest_world}", "FILE")
    shutil.copytree(src_world, dest_world)

    # 2. 加载缓存（仅作辅助）
    cache = load_usercache(src_world)
    log(f"从 usercache 加载了 {len(cache)} 条记录", "CACHE")

    # 3. 确定要处理的玩家名列表
    names_to_process = set()

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
            else:
                log(f"无法识别 UUID: {uuid_old}，如果这是您的账号，请在手动输入框中填写玩家名", "WARN")

    # 4. 为每个玩家名生成双副本
    dual_count = 0
    if names_to_process:
        for name in names_to_process:
            offline_uuid = get_offline_uuid_str(name)
            online_uuid = get_online_uuid(name, log) if not offline_mode else None

            # 确保 playerdata 目录存在
            pd.mkdir(exist_ok=True)

            # 生成离线副本（如果还没有）
            offline_file = pd / f"{offline_uuid}.dat"
            if not offline_file.exists():
                # 寻找任意一个现有 dat 文件作为模板（通常第一个即可）
                template_file = next(pd.glob("*.dat"), None)
                if template_file:
                    shutil.copy2(template_file, offline_file)
                    dual_count += 1
                    log(f"生成离线副本: {offline_uuid}.dat (玩家 {name})")
                else:
                    log(f"警告: playerdata 目录为空，无法为 {name} 创建离线副本", "WARN")

            # 生成正版副本（如果获取到了正版UUID）
            if online_uuid:
                online_file = pd / f"{online_uuid}.dat"
                if not online_file.exists():
                    template_file = next(pd.glob("*.dat"), None)
                    if template_file:
                        shutil.copy2(template_file, online_file)
                        dual_count += 1
                        log(f"生成正版副本: {online_uuid}.dat (玩家 {name})")
        log(f"共生成 {dual_count} 个双UUID副本", "INFO")
    else:
        log("未找到任何玩家数据，跳过双UUID生成", "WARN")

    # 5. 精简存档
    if do_clean:
        log("正在精简存档...", "CLEAN")
        clean_world(dest_world, log)
    else:
        log("跳过精简步骤", "INFO")

    # 6. 修改 server.properties
    update_server_properties(dest_dir, world_name, log)

def update_server_properties(dest_dir, world_name, log):
    props = dest_dir / "server.properties"
    if props.exists():
        lines = props.read_text(encoding='utf-8').splitlines()
        new_lines = []
        found = False
        for line in lines:
            if line.startswith("level-name="):
                new_lines.append(f"level-name={world_name}")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"level-name={world_name}")
        props.write_text("\n".join(new_lines), encoding='utf-8')
        log(f"已更新 server.properties: level-name={world_name}", "CONFIG")