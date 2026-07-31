import hashlib
import json
import struct
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.constants import MinecraftConstants
from core.io_atomic import atomic_write_text
from core.logger import logger
from core.types import LogCallback, UUIDMapping

# requests 延迟导入：仅联网查询 Mojang API 时需要（启动期不联网），
# 避免启动时拉入 requests + urllib3 + idna 等重库。
# （参照项目内 anvil/Pillow 已有的函数内延迟导入先例。）
requests = None  # type: ignore

_session = None
_session_lock = threading.Lock()


def _ensure_requests():
    """惰性导入 requests，仅首次联网时执行。"""
    global requests
    if requests is None:
        import requests as _requests  # type: ignore
        requests = _requests
    return requests


def _ensure_session() -> Any:
    """返回进程级共享请求会话（keep-alive 连接复用）。

    每次请求复用同一个 Session，避免重复 DNS + TCP + TLS 握手；
    批量查询（如玩家列表名称解析）可显著降低延迟与 CPU。
    """
    global _session
    if _session is None:
        with _session_lock:
            if _session is None:
                _session = _ensure_requests().Session()
    return _session


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
    """联网获取正版 UUID 和官方大小写玩家名。

    Args:
        name: 玩家名。
        log_callback: 可选日志回调。

    Returns:
        tuple: ``(uuid_str, official_name)``；失败为 ``(None, None)``。
    """
    if log_callback:
        log_callback(f"正在查询正版UUID: {name} ...", "API")
    try:
        url = f"{MinecraftConstants.MOJANG_PROFILE_URL}{name}"
        response = _ensure_session().get(url, timeout=5)
        if response.status_code != 200:
            if log_callback:
                log_callback(
                    f"API返回非200状态码: {response.status_code}",
                    "WARN",
                )
            return None, None
        data = response.json()
        raw = str(data["id"])
        official_name = str(data.get("name", name))
        uuid_str = (
            f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-"
            f"{raw[16:20]}-{raw[20:32]}"
        )
        if log_callback:
            log_callback(
                f"正版UUID获取成功: {uuid_str} (官方名称: {official_name})",
                "API",
            )
        return uuid_str, official_name
    except (OSError, ValueError, TypeError, KeyError) as exc:
        if log_callback:
            log_callback(f"API请求失败: {exc}", "ERROR")
    except Exception as exc:
        # requests 可能抛出 RequestException 等网络错误。
        if log_callback:
            log_callback(f"API请求失败: {exc}", "ERROR")
    return None, None


@dataclass(frozen=True)
class NameHistoryEntry:
    """Mojang 姓名历史中的一条记录。

    Attributes:
        name: 该时间段使用的玩家名。
        changed_to_at: 改为该名字的 Unix 毫秒时间戳；当前名没有该字段。
    """

    name: str
    changed_to_at: Optional[int] = None


_NAME_CACHE_DIR = Path.home() / ".mc_save_helper"
_NAME_CACHE_PATH = _NAME_CACHE_DIR / "uuid_name_cache.json"
_CACHE_VERSION = 1


@dataclass(frozen=True)
class NameCacheEntry:
    """一条 UUID 的本地缓存：姓名历史与缓存时刻。"""

    history: Tuple[NameHistoryEntry, ...]
    cached_at: float

    @property
    def current_name(self) -> Optional[str]:
        """缓存中的当前玩家名（历史最后一项）。"""
        if not self.history:
            return None
        return self.history[-1].name


class UuidNameCache:
    """UUID → 玩家名查询结果的本地磁盘缓存。

    数据保存在 ``~/.mc_save_helper/uuid_name_cache.json``，写盘使用同目录
    临时文件 + ``os.replace`` 原子替换；加载或写入失败只影响缓存本身，
    不影响查询成功/失败语义。
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        """创建缓存；磁盘读取延迟到首次访问。

        Args:
            path: 缓存文件路径；缺省 ``~/.mc_save_helper/uuid_name_cache.json``。
        """
        self._path = path or _NAME_CACHE_PATH
        self._lock = threading.Lock()
        self._entries: Dict[str, NameCacheEntry] = {}
        self._loaded = False

    def get(self, uuid_norm: str) -> Optional[NameCacheEntry]:
        """返回规范化 UUID 的缓存条目；缺失时为 None。"""
        self._ensure_loaded()
        with self._lock:
            return self._entries.get(uuid_norm)

    def remember(
        self,
        uuid_norm: str,
        history: Sequence[NameHistoryEntry],
    ) -> None:
        """缓存一条查询结果并落盘；失败仅记录调试日志。"""
        if not history:
            return
        entry = NameCacheEntry(history=tuple(history), cached_at=time.time())
        with self._lock:
            self._ensure_loaded_locked()
            self._entries[uuid_norm] = entry
            self._persist_locked()

    def clear(self) -> None:
        """清空内存缓存并删除磁盘文件。"""
        with self._lock:
            self._entries.clear()
            try:
                self._path.unlink(missing_ok=True)
            except OSError as exc:
                logger.debug(
                    f"删除 UUID 名称缓存失败: {exc}",
                    module="UuidNameCache",
                )

    def _ensure_loaded(self) -> None:
        with self._lock:
            self._ensure_loaded_locked()

    def _ensure_loaded_locked(self) -> None:
        """持锁时惰性读取磁盘缓存；损坏或缺失时按空缓存处理。"""
        if self._loaded:
            return
        self._loaded = True
        try:
            with open(self._path, "r", encoding="utf-8") as stream:
                data = json.load(stream)
        except FileNotFoundError:
            return
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.debug(
                f"UUID 名称缓存加载失败，将重新开始: {exc}",
                module="UuidNameCache",
            )
            return
        if not isinstance(data, dict):
            return
        entries = data.get("entries")
        if not isinstance(entries, dict):
            return
        for raw_uuid, raw_entry in entries.items():
            if not isinstance(raw_entry, dict):
                continue
            history = _parse_cached_history(raw_entry.get("history"))
            if not history:
                continue
            cached_at = raw_entry.get("cached_at", 0.0)
            try:
                cached_at = float(cached_at)
            except (TypeError, ValueError):
                cached_at = 0.0
            self._entries[str(raw_uuid)] = NameCacheEntry(
                history=tuple(history),
                cached_at=cached_at,
            )

    def _persist_locked(self) -> None:
        """持锁时把内存缓存原子写入磁盘。"""
        payload = {
            "version": _CACHE_VERSION,
            "entries": {
                uuid_norm: {
                    "cached_at": entry.cached_at,
                    "history": [
                        {"name": item.name, "changed_to_at": item.changed_to_at}
                        for item in entry.history
                    ],
                }
                for uuid_norm, entry in self._entries.items()
            },
        }
        try:
            content = json.dumps(payload, ensure_ascii=False, indent=2)
            atomic_write_text(self._path, content)
        except OSError as exc:
            logger.debug(
                f"UUID 名称缓存写入失败: {exc}",
                module="UuidNameCache",
            )


def _parse_cached_history(raw_history: object) -> List[NameHistoryEntry]:
    """解析持久化的历史数组；跳过畸形条目。"""
    entries: List[NameHistoryEntry] = []
    if not isinstance(raw_history, list):
        return entries
    for item in raw_history:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        changed: Optional[int] = None
        raw = item.get("changed_to_at")
        if isinstance(raw, int) and not isinstance(raw, bool):
            changed = raw
        elif isinstance(raw, str) and raw.isdigit():
            changed = int(raw)
        entries.append(NameHistoryEntry(name=name, changed_to_at=changed))
    return entries


# 模块级共享缓存实例：磁盘访问惰性，不影响启动。
_name_cache = UuidNameCache()


def get_name_history(
    uuid: str,
    log_callback: Optional[LogCallback] = None,
) -> Optional[List[NameHistoryEntry]]:
    """通过 Mojang 官方 API 查询玩家的曾用名与当前名。

    优先使用 ``https://api.mojang.com/user/profiles/{uuid}/names``，要求
    UUID 不带连字符；返回数组按时间从旧到新排列，最后一项为当前名。
    从未改名的玩家在该端点没有历史记录（返回 404），此时回退到会话服务器
    （方法一）获取当前名，返回单条记录。

    Args:
        uuid: 玩家 UUID（带不带连字符均可）。
        log_callback: 可选日志回调。

    Returns:
        姓名历史列表；UUID 无效、两次请求均失败或玩家不存在时返回 None。
    """
    clean = normalize_uuid(uuid)
    if len(clean) != 32:
        if log_callback:
            log_callback(f"无效的 UUID: {uuid}", "WARN")
        return None
    cached = _name_cache.get(clean)
    if cached is not None:
        if log_callback:
            log_callback(f"命中本地缓存: {cached.current_name}", "CACHE")
        return list(cached.history) or None
    if log_callback:
        log_callback(f"正在查询姓名历史: {clean} ...", "API")
    entries = _fetch_name_history(clean, log_callback)
    if entries:
        _name_cache.remember(clean, entries)
        if log_callback:
            current = entries[-1].name if entries else None
            suffix = f"（当前名: {current}）" if current else ""
            log_callback(
                f"姓名历史查询成功: {len(entries)} 条{suffix}",
                "API",
            )
        return entries
    # 从未改名的玩家没有姓名历史记录，回退到会话服务器查询当前名。
    current = _fetch_current_name(clean, log_callback)
    if current:
        _name_cache.remember(clean, [NameHistoryEntry(name=current)])
        if log_callback:
            log_callback(
                f"姓名历史端点未找到记录，已从会话服务器获取当前名: {current}",
                "API",
            )
        return [NameHistoryEntry(name=current)]
    return None


def _fetch_name_history(
    clean: str,
    log_callback: Optional[LogCallback],
) -> Optional[List[NameHistoryEntry]]:
    """请求 names 端点并解析为类型化记录。"""
    try:
        url = f"{MinecraftConstants.MOJANG_NAMES_URL}{clean}/names"
        response = _ensure_session().get(url, timeout=5)
        if response.status_code != 200:
            if log_callback:
                log_callback(
                    f"API返回非200状态码: {response.status_code}",
                    "WARN",
                )
            return None
        data = response.json()
        return _parse_name_history(data) or None
    except (OSError, ValueError, TypeError, KeyError) as exc:
        if log_callback:
            log_callback(f"API请求失败: {exc}", "ERROR")
    except Exception as exc:
        # requests 可能抛出 RequestException 等网络错误。
        if log_callback:
            log_callback(f"API请求失败: {exc}", "ERROR")
    return None


def _fetch_current_name(
    clean: str,
    log_callback: Optional[LogCallback],
) -> Optional[str]:
    """通过会话服务器查询玩家当前名（方法一端点）。"""
    try:
        url = f"{MinecraftConstants.MOJANG_SESSION_SERVER_URL}{clean}"
        response = _ensure_session().get(url, timeout=5)
        if response.status_code != 200:
            if log_callback:
                log_callback(
                    f"API返回非200状态码: {response.status_code}",
                    "WARN",
                )
            return None
        name = response.json().get("name")
        return str(name) if name else None
    except (OSError, ValueError, TypeError, KeyError) as exc:
        if log_callback:
            log_callback(f"API请求失败: {exc}", "ERROR")
    except Exception as exc:
        # requests 可能抛出 RequestException 等网络错误。
        if log_callback:
            log_callback(f"API请求失败: {exc}", "ERROR")
    return None


def _parse_name_history(data: object) -> List[NameHistoryEntry]:
    """把 Mojang names API 的 JSON 数组解析为类型化记录。"""
    entries: List[NameHistoryEntry] = []
    if not isinstance(data, list):
        return entries
    for item in data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        changed: Optional[int] = None
        raw = item.get("changedToAt")
        if isinstance(raw, int) and not isinstance(raw, bool):
            changed = raw
        elif isinstance(raw, str) and raw.isdigit():
            changed = int(raw)
        entries.append(NameHistoryEntry(name=name, changed_to_at=changed))
    return entries


def get_current_name(
    uuid: str,
    log_callback: Optional[LogCallback] = None,
) -> Optional[str]:
    """通过会话服务器查询玩家当前名（单请求，带本地缓存）。

    优先命中本地缓存；未命中时只发起一次会话服务器请求，适合玩家列表
    这类只需要当前名的批量场景。

    Args:
        uuid: 玩家 UUID（带不带连字符均可）。
        log_callback: 可选日志回调。

    Returns:
        当前玩家名；UUID 无效或查询失败时返回 None。
    """
    clean = normalize_uuid(uuid)
    if len(clean) != 32:
        if log_callback:
            log_callback(f"无效的 UUID: {uuid}", "WARN")
        return None
    cached = _name_cache.get(clean)
    if cached is not None and cached.current_name:
        if log_callback:
            log_callback(f"命中本地缓存: {cached.current_name}", "CACHE")
        return cached.current_name
    name = _fetch_current_name(clean, log_callback)
    if name:
        _name_cache.remember(clean, [NameHistoryEntry(name=name)])
        if log_callback:
            log_callback(f"查询到玩家名: {name}", "API")
    return name


def get_name_from_uuid(
    uuid: str,
    log_callback: Optional[LogCallback] = None
) -> Optional[str]:
    """通过 UUID 查询官方玩家名（兼容入口，保留迁移扫描限速）。

    Args:
        uuid: UUID 字符串。
        log_callback: 可选日志回调。

    Returns:
        str | None: 官方玩家名；失败为 None。
    """
    if log_callback:
        log_callback(f"正在通过UUID查询玩家名: {uuid} ...", "API")
    clean = normalize_uuid(uuid)
    if len(clean) != 32:
        if log_callback:
            log_callback(f"无效的 UUID: {uuid}", "WARN")
        return None
    name = get_current_name(clean, log_callback)
    # 批量迁移扫描时保留原有的限速节奏。
    time.sleep(0.3)
    return name


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
