"""UUID 服务 —— 封装 UUID 生成/查询逻辑"""
from typing import Optional, Tuple, Callable

from core.uuid_utils import (
    get_offline_uuid_str,
    get_online_uuid,
    get_name_from_uuid,
    load_usercache,
    build_mappings,
)
from core.types import LogCallback, UUIDMapping


class UUIDService:
    """UUID 相关操作服务"""

    @staticmethod
    def generate_offline_uuid(player_name: str) -> str:
        """生成离线 UUID"""
        return get_offline_uuid_str(player_name)

    @staticmethod
    def query_online_uuid(
        name: str,
        log_callback: Optional[LogCallback] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        """联网查询正版 UUID

        Returns:
            (uuid_str, official_name) 或 (None, None)
        """
        return get_online_uuid(name, log_callback)

    @staticmethod
    def query_name_from_uuid(uuid: str, log_callback: Optional[LogCallback] = None) -> Optional[str]:
        """通过 UUID 反查玩家名"""
        return get_name_from_uuid(uuid, log_callback)

    @staticmethod
    def load_usercache(world_path) -> dict:
        """加载 usercache.json"""
        return load_usercache(world_path)

    @staticmethod
    def build_mappings(
        world_path,
        cache: dict,
        offline_mode: bool,
        manual_names: Optional[list],
        log: LogCallback
    ) -> list:
        """构建 UUID 映射列表"""
        return build_mappings(world_path, cache, offline_mode, manual_names, log)
