import hashlib
import json
import struct
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

from core.types import LogCallback
from core.constants import MinecraftConstants


def get_offline_uuid_str(name: str) -> str:
    """生成离线 UUID 字符串

    Args:
        name: 玩家名

    Returns:
        格式化的 UUID 字符串 (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)
    """
    digest = bytearray(
        hashlib.md5(
            f"OfflinePlayer:{name}".encode('utf-8')).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30
    digest[8] = (digest[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(digest)))


def uuid_to_ints(uuid_str: str) -> List[int]:
    """将 UUID 字符串转换为 4 个整数

    Args:
        uuid_str: UUID 字符串

    Returns:
        包含 4 个整数的列表
    """
    hex_s = uuid_str.replace("-", "")
    values = []
    for i in range(0, 32, 8):
        value = int(hex_s[i:i + 8], 16)
        if value >= 0x80000000:
            value -= 0x100000000
        values.append(value)
    return values


def uuid_to_most_least(uuid_str: str) -> Tuple[int, int]:
    """将 UUID 字符串转换为 Most/Least 整数对

    Args:
        uuid_str: UUID 字符串

    Returns:
        (Most, Least) 整数对
    """
    hex_s = uuid_str.replace("-", "")
    high = int(hex_s[:16], 16)
    low = int(hex_s[16:], 16)
    return struct.unpack('>q', struct.pack('>Q', high))[0], \
        struct.unpack('>q', struct.pack('>Q', low))[0]


def get_online_uuid(
    name: str,
    log_callback: Optional[LogCallback] = None
) -> Tuple[Optional[str], Optional[str]]:
    """
    联网获取正版 UUID 和官方大小写玩家名。

    Args:
        name: 玩家名
        log_callback: 可选的日志回调函数

    Returns:
        (uuid_str, official_name) 或 (None, None)
    """
    if log_callback:
        log_callback(f"正在查询正版UUID: {name} ...", "API")
    try:
        url = f"{MinecraftConstants.MOJANG_PROFILE_URL}{name}"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            data = r.json()
            raw = data['id']
            official_name = data.get('name', name)  # Mojang 返回的官方大小写
            uuid_str = f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"
            if log_callback:
                log_callback(
                    f"正版UUID获取成功: {uuid_str} (官方名称: {official_name})", "API")
            return uuid_str, official_name
        else:
            if log_callback:
                log_callback(f"API返回非200状态码: {r.status_code}", "WARN")
    except Exception as e:
        if log_callback:
            log_callback(f"API请求失败: {e}", "ERROR")
    return None, None


def get_name_from_uuid(
    uuid: str,
    log_callback: Optional[LogCallback] = None
) -> Optional[str]:
    """通过 UUID 查询官方玩家名

    Args:
        uuid: UUID 字符串
        log_callback: 可选的日志回调函数

    Returns:
        玩家名或 None
    """
    if log_callback:
        log_callback(f"正在通过UUID查询玩家名: {uuid} ...", "API")
    try:
        url = f"https://sessionserver.mojang.com/session/minecraft/profile/{
            uuid.replace(
                '-',
                '')}"
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


def load_usercache(world_path: Path) -> dict:
    """加载 usercache.json 文件

    Args:
        world_path: 世界存档路径

    Returns:
        UUID 到玩家名的映射字典
    """
    cache: dict = {}
    for p in [
        world_path.parent /
        "usercache.json",
        world_path.parent.parent /
            "usercache.json"]:
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


def build_mappings(
    world_path: Path,
    cache: dict,
    offline_mode: bool,
    manual_names: Optional[List[str]],
    log: LogCallback,
    custom_mappings: Optional[Dict[str, str]] = None,
) -> List[Tuple[List[int], List[int], str, str, Tuple[int, int], Tuple[int, int]]]:
    """构建 UUID 映射列表

    Args:
        world_path: 世界存档路径
        cache: UUID 缓存字典
        offline_mode: 是否离线模式
        manual_names: 手动指定的玩家名列表
        log: 日志回调函数
        custom_mappings: 玩家名称到自定义 UUID 的映射

    Returns:
        UUID 映射列表
    """
    pd = world_path / "playerdata"
    if not pd.exists():
        return []
    maps: List[Tuple[List[int], List[int], str,
                     str, Tuple[int, int], Tuple[int, int]]] = []
    new_uuids = set()
    processed_names = set()

    # 处理自定义UUID映射
    custom_mappings = custom_mappings or {}
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
            processed_names.add(name)
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
            log(f"映射: {name} ({old_u} -> {new_u})", "INFO")
        else:
            log(f"无法识别玩家 UUID: {old_u}，已跳过", "WARN")

    # 处理手动输入但不在playerdata中的玩家
    if manual_names:
        for name in manual_names:
            if name not in processed_names:  # 检查是否已经处理过
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
                    uuid_to_ints(offline_uuid),
                    uuid_to_ints(new_u),
                    offline_uuid,
                    new_u,
                    uuid_to_most_least(offline_uuid),
                    uuid_to_most_least(new_u)
                ))

    return maps
