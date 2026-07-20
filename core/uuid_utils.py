import hashlib
import json
import struct
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.types import LogCallback, UUIDMapping
from core.constants import MinecraftConstants

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


def normalize_uuid(uuid_str: str) -> str:
    """Normalize a UUID to 32 lowercase hex chars without hyphens.

    Non-string or empty values return ``""`` so callers can guard once.
    """
    if not uuid_str or not isinstance(uuid_str, str):
        return ""
    return uuid_str.replace("-", "").lower()


def format_uuid_with_hyphens(uuid_str: str) -> str:
    """Format a UUID as 8-4-4-4-12 lowercase hex.

    Returns the normalized 32-char form when length is not 32, or ``""`` when
    empty after normalization.
    """
    normalized = normalize_uuid(uuid_str)
    if not normalized:
        return ""
    if len(normalized) != 32:
        return normalized
    return (
        f"{normalized[:8]}-{normalized[8:12]}-{normalized[12:16]}-"
        f"{normalized[16:20]}-{normalized[20:]}"
    )


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
    all_dat_files = _find_player_dat_files(world_path)
    if not all_dat_files:
        return []

    custom_mappings = custom_mappings or {}
    if custom_mappings:
        log(f"检测到 {len(custom_mappings)} 个自定义UUID映射", "INFO")
    maps, unresolved = _map_known_players(
        all_dat_files, cache, offline_mode, custom_mappings, log
    )

    if manual_names:
        _append_manual_mappings(maps, unresolved, manual_names, custom_mappings, log)
    elif unresolved:
        _log_unresolved(unresolved, log)

    _validate_unique_targets(maps)
    return maps


def _find_player_dat_files(world_path: Path) -> List[Path]:
    from core.utils import list_player_dat_files

    return list_player_dat_files(world_path)


def _map_known_players(
    files: List[Path],
    cache: dict,
    offline_mode: bool,
    custom_mappings: Dict[str, str],
    log: LogCallback,
) -> Tuple[List[UUIDMapping], List[str]]:
    maps: List[UUIDMapping] = []
    new_uuids: set[str] = set()
    unresolved: List[str] = []
    for player_file in files:
        old_uuid = player_file.stem
        if old_uuid in new_uuids:
            continue
        name = _resolve_player_name(old_uuid, cache, offline_mode, log)
        if not name:
            unresolved.append(old_uuid)
            continue
        new_uuid = _target_uuid_for_name(name, custom_mappings, log)
        maps.append(_make_uuid_mapping(old_uuid, new_uuid))
        new_uuids.add(new_uuid)
        log(f"映射: {name} ({old_uuid} -> {new_uuid})", "INFO")
    return maps, unresolved


def _append_manual_mappings(
    maps: List[UUIDMapping],
    unresolved: List[str],
    manual_names: List[str],
    custom_mappings: Dict[str, str],
    log: LogCallback,
) -> None:
    names = [name.strip() for name in manual_names if name.strip()]
    if len(names) != len(unresolved) or len(set(names)) != len(names):
        raise ValueError(
            f"未知玩家数量为 {len(unresolved)}，手动名称数量为 {len(names)}，"
            "必须一对一且名称不能重复"
        )
    for old_uuid, name in zip(sorted(unresolved), names):
        new_uuid = _target_uuid_for_name(name, custom_mappings, log)
        maps.append(_make_uuid_mapping(old_uuid, new_uuid))
        log(f"手动映射: {name} ({old_uuid} -> {new_uuid})", "MANUAL")


def _log_unresolved(unresolved: List[str], log: LogCallback) -> None:
    for old_uuid in unresolved:
        log(f"无法识别玩家 UUID: {old_uuid}，已跳过", "WARN")


def _validate_unique_targets(maps: List[UUIDMapping]) -> None:
    target_owners: Dict[str, str] = {}
    for mapping in maps:
        old_uuid, new_uuid = mapping[2], mapping[3]
        owner = target_owners.get(new_uuid)
        if owner is not None and owner != old_uuid:
            raise ValueError(f"多个玩家映射到了同一个目标 UUID: {new_uuid}")
        target_owners[new_uuid] = old_uuid
