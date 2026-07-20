"""UUID 服务 —— 封装 UUID 生成/查询逻辑"""
from typing import Optional, Tuple

from core.uuid_utils import (
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
