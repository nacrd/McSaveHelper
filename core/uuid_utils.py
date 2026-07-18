import hashlib
import json
import struct
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.types import LogCallback, UUIDMapping
from core.constants import MinecraftConstants
from core.utils import find_player_data_dirs

# requests 延迟导入：仅联网查询 Mojang API 时需要（启动期不联网），
# 避免启动时拉入 requests + urllib3 + idna 等重库。
# （参照项目内 anvil/Pillow 已有的函数内延迟导入先例。）
requests = None  # type: ignore


def _ensure_requests():
    """惰性导入 requests，仅首次联网时执行。"""
    global requests
    if requests is None:
        import requests as _requests  # type: ignore
        requests = _requests
    return requests


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
        r = _ensure_requests().get(url, timeout=5)
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
        r = _ensure_requests().get(url, timeout=5)
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
        world_path.parent / "usercache.json",
        world_path.parent.parent / "usercache.json",
    ]:
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


def _make_uuid_mapping(old_uuid: str, new_uuid: str) -> UUIDMapping:
    return (
        uuid_to_ints(old_uuid),
        uuid_to_ints(new_uuid),
        old_uuid,
        new_uuid,
        uuid_to_most_least(old_uuid),
        uuid_to_most_least(new_uuid),
    )


def _resolve_player_name(
    old_uuid: str,
    cache: dict,
    offline_mode: bool,
    log: LogCallback,
) -> Optional[str]:
    name = cache.get(old_uuid)
    if not name and not offline_mode:
        name = get_name_from_uuid(old_uuid, log)
    return name


def _target_uuid_for_name(
    name: str,
    custom_mappings: Dict[str, str],
    log: LogCallback,
) -> str:
    custom_uuid = custom_mappings.get(name)
    if custom_uuid:
        log(f"使用自定义UUID映射: {name} -> {custom_uuid}", "SUCCESS")
        return custom_uuid
    return get_offline_uuid_str(name)


def build_mappings(
    world_path: Path,
    cache: dict,
    offline_mode: bool,
    manual_names: Optional[List[str]],
    log: LogCallback,
    custom_mappings: Optional[Dict[str, str]] = None,
) -> List[UUIDMapping]:
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
    pd_dirs = find_player_data_dirs(world_path)
    all_dat_files = []
    for pd in pd_dirs:
        all_dat_files.extend(pd.glob("*.dat"))
    if not all_dat_files:
        return []
    maps: List[UUIDMapping] = []
    new_uuids: set[str] = set()
    unresolved: List[str] = []

    # 处理自定义UUID映射
    custom_mappings = custom_mappings or {}
    if custom_mappings:
        log(f"检测到 {len(custom_mappings)} 个自定义UUID映射", "INFO")

    for f in all_dat_files:
        old_u = f.stem
        if old_u in new_uuids:
            continue

        name = _resolve_player_name(
            old_u,
            cache,
            offline_mode,
            log,
        )

        if name:
            new_u = _target_uuid_for_name(name, custom_mappings, log)
            maps.append(_make_uuid_mapping(old_u, new_u))
            new_uuids.add(new_u)
            log(f"映射: {name} ({old_u} -> {new_u})", "INFO")
        else:
            unresolved.append(old_u)

    if manual_names:
        names = [name.strip() for name in manual_names if name.strip()]
        if len(names) != len(unresolved) or len(set(names)) != len(names):
            raise ValueError(
                f"未知玩家数量为 {len(unresolved)}，手动名称数量为 {len(names)}，"
                "必须一对一且名称不能重复"
            )
        for old_u, name in zip(sorted(unresolved), names):
            new_u = _target_uuid_for_name(name, custom_mappings, log)
            maps.append(_make_uuid_mapping(old_u, new_u))
            new_uuids.add(new_u)
            log(f"手动映射: {name} ({old_u} -> {new_u})", "MANUAL")
    elif unresolved:
        for old_u in unresolved:
            log(f"无法识别玩家 UUID: {old_u}，已跳过", "WARN")

    target_owners: Dict[str, str] = {}
    for mapping in maps:
        old_u, new_u = mapping[2], mapping[3]
        owner = target_owners.get(new_u)
        if owner is not None and owner != old_u:
            raise ValueError(f"多个玩家映射到了同一个目标 UUID: {new_u}")
        target_owners[new_u] = old_u
    return maps
