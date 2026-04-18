import hashlib
import json
import struct
import time

import requests

from .config import config_manager


def get_offline_uuid_str(name):
    md5 = hashlib.md5(f"OfflinePlayer:{name}".encode('utf-8')).hexdigest()
    return f"{md5[:8]}-{md5[8:12]}-{md5[12:16]}-{md5[16:20]}-{md5[20:32]}"

def uuid_to_ints(uuid_str):
    hex_s = uuid_str.replace("-", "")
    return [int(hex_s[i:i+8], 16) for i in range(0, 32, 8)]

def uuid_to_most_least(uuid_str):
    hex_s = uuid_str.replace("-", "")
    high = int(hex_s[:16], 16)
    low = int(hex_s[16:], 16)
    return struct.unpack('>q', struct.pack('>Q', high))[0], \
           struct.unpack('>q', struct.pack('>Q', low))[0]

def get_online_uuid(name, log_callback=None):
    """
    联网获取正版 UUID 和官方大小写玩家名。
    返回: (uuid_str, official_name) 或 (None, None)
    """
    if log_callback:
        log_callback(f"正在查询正版UUID: {name} ...", "API")
    try:
        url = f"https://api.mojang.com/users/profiles/minecraft/{name}"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            data = r.json()
            raw = data['id']
            official_name = data.get('name', name)  # Mojang 返回的官方大小写
            uuid_str = f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"
            if log_callback:
                log_callback(f"正版UUID获取成功: {uuid_str} (官方名称: {official_name})", "API")
            return uuid_str, official_name
        else:
            if log_callback:
                log_callback(f"API返回非200状态码: {r.status_code}", "WARN")
    except Exception as e:
        if log_callback:
            log_callback(f"API请求失败: {e}", "ERROR")
    return None, None

def get_name_from_uuid(uuid, log_callback=None):
    """通过 UUID 查询官方玩家名"""
    if log_callback:
        log_callback(f"正在通过UUID查询玩家名: {uuid} ...", "API")
    try:
        url = f"https://sessionserver.mojang.com/session/minecraft/profile/{uuid.replace('-', '')}"
        r = requests.get(url, timeout=5)
        time.sleep(0.3)
        if r.status_code == 200:
            name = r.json().get("name")
            if log_callback:
                log_callback(f"查询到玩家名: {name}", "API")
            return name
        else:
            if log_callback:
                log_callback(f"API返回非200状态码: {r.status_code}", "WARN")
    except Exception as e:
        if log_callback:
            log_callback(f"API请求失败: {e}", "ERROR")
    return None

def load_usercache(world_path):
    cache = {}
    for p in [world_path.parent / "usercache.json", world_path.parent.parent / "usercache.json"]:
        if p.exists():
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for entry in data:
                        if 'uuid' in entry and 'name' in entry:
                            cache[entry['uuid']] = entry['name']
            except (OSError, json.JSONDecodeError, KeyError):
                pass
    return cache

def build_mappings(world_path, cache, offline_mode, manual_names, log):
    pd = world_path / "playerdata"
    if not pd.exists():
        return []
    maps = []
    new_uuids = set()
    
    # 处理自定义UUID映射
    custom_mappings = config_manager.config["custom_uuid_mappings"]
    if custom_mappings:
        log(f"检测到 {len(custom_mappings)} 个自定义UUID映射", "INFO")
    
    for f in pd.glob("*.dat"):
        old_u = f.stem
        if old_u in new_uuids:
            continue
        
        name = cache.get(old_u)
        if not name and not offline_mode:
            name = get_name_from_uuid(old_u, log)
        
        # 检查是否有自定义UUID映射
        custom_uuid = None
        if name and name in custom_mappings:
            custom_uuid = custom_mappings[name]
            log(f"使用自定义UUID映射: {name} -> {custom_uuid}", "SUCCESS")
        
        if not name and manual_names:
            name = manual_names[0]
            log(f"使用手动输入的玩家名: {name}", "MANUAL")
            # 检查手动输入的玩家名是否有自定义映射
            if name in custom_mappings:
                custom_uuid = custom_mappings[name]
                log(f"使用自定义UUID映射: {name} -> {custom_uuid}", "SUCCESS")
        
        if name:
            # 优先使用自定义UUID，否则使用离线UUID
            if custom_uuid:
                new_u = custom_uuid
            else:
                new_u = get_offline_uuid_str(name)
            
            maps.append((
                uuid_to_ints(old_u),
                uuid_to_ints(new_u),
                old_u,
                new_u,
                uuid_to_most_least(old_u),
                uuid_to_most_least(new_u)
            ))
            new_uuids.add(new_u)
            log(f"映射: {name} ({old_u} -> {new_u})")
        else:
            log(f"无法识别玩家 UUID: {old_u}，已跳过", "WARN")
    
    # 处理手动输入但不在playerdata中的玩家
    if manual_names:
        for name in manual_names:
            if name not in [m[2] for m in maps]:  # 检查是否已经处理过
                custom_uuid = custom_mappings.get(name)
                if custom_uuid:
                    new_u = custom_uuid
                    log(f"为手动玩家 {name} 使用自定义UUID: {new_u}", "SUCCESS")
                else:
                    new_u = get_offline_uuid_str(name)
                    log(f"为手动玩家 {name} 生成离线UUID: {new_u}", "INFO")
                
                # 添加一个虚拟映射（仅用于生成双UUID文件）
                offline_uuid = get_offline_uuid_str(name)
                maps.append((
                    uuid_to_ints(offline_uuid),  # 使用离线UUID作为旧UUID
                    uuid_to_ints(new_u),         # 新UUID
                    offline_uuid,
                    new_u,
                    uuid_to_most_least(offline_uuid),
                    uuid_to_most_least(new_u)
                ))
    
    return maps