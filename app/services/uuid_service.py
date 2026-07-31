"""UUID 服务 —— 封装 UUID 生成/查询逻辑"""
from typing import List, Optional, Tuple

from core.uuid_utils import (
    NameHistoryEntry,
    get_current_name,
    get_name_history,
    get_offline_uuid_str,
    get_online_uuid,
)
from core.types import LogCallback


class UUIDService:
    """UUID 相关操作服务

    提供迁移界面使用的离线 UUID 生成与正版 UUID 查询。
    """

    @staticmethod
    def generate_offline_uuid(player_name: str) -> str:
        """生成离线 UUID

        根据玩家名称生成离线模式UUID。

        Args:
            player_name: 玩家名称

        Returns:
            str: 生成的离线UUID字符串
        """
        return get_offline_uuid_str(player_name)

    @staticmethod
    def query_online_uuid(
        name: str,
        log_callback: Optional[LogCallback] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        """联网查询正版 UUID

        通过Mojang API查询正版玩家的UUID和官方名称。

        Args:
            name: 玩家名称
            log_callback: 可选的日志回调函数

        Returns:
            Tuple[Optional[str], Optional[str]]: 包含UUID字符串和官方名称的元组，
                如果查询失败则返回(None, None)
        """
        return get_online_uuid(name, log_callback)

    @staticmethod
    def query_name_history(
        uuid: str,
        log_callback: Optional[LogCallback] = None,
    ) -> Optional[List[NameHistoryEntry]]:
        """联网查询玩家曾用名与当前名。

        Args:
            uuid: 玩家 UUID（带不带连字符均可）。
            log_callback: 可选的日志回调函数。

        Returns:
            按时间从旧到新的姓名历史列表，最后一项为当前名；
            请求失败或玩家不存在时返回 None。
        """
        return get_name_history(uuid, log_callback)

    @staticmethod
    def query_current_name(
        uuid: str,
        log_callback: Optional[LogCallback] = None,
    ) -> Optional[str]:
        """联网查询玩家当前名（单请求，优先命中本地缓存）。

        适合玩家列表等只需要当前名的批量场景；缓存命中时不再联网。

        Args:
            uuid: 玩家 UUID（带不带连字符均可）。
            log_callback: 可选的日志回调函数。

        Returns:
            当前玩家名；UUID 无效或查询失败时返回 None。
        """
        return get_current_name(uuid, log_callback)
