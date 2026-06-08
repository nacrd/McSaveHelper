"""UUID 服务 —— 封装 UUID 生成/查询逻辑"""
from typing import Dict, Optional, Tuple
from pathlib import Path

from core.uuid_utils import (
    get_offline_uuid_str,
    get_online_uuid,
    get_name_from_uuid,
    load_usercache,
    build_mappings,
)
from core.types import LogCallback


class UUIDService:
    """UUID 相关操作服务

    提供UUID生成、查询、映射构建等功能。
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
    def query_name_from_uuid(
            uuid: str,
            log_callback: Optional[LogCallback] = None) -> Optional[str]:
        """通过 UUID 反查玩家名称

        通过Mojang API根据UUID查询对应的玩家名称。

        Args:
            uuid: 玩家UUID字符串
            log_callback: 可选的日志回调函数

        Returns:
            Optional[str]: 玩家名称，如果查询失败则返回None
        """
        return get_name_from_uuid(uuid, log_callback)

    @staticmethod
    def load_usercache(world_path: Path) -> dict:
        """加载 usercache.json

        从世界存档目录加载用户缓存文件。

        Args:
            world_path: 世界存档目录路径

        Returns:
            dict: 用户缓存数据字典
        """
        return load_usercache(world_path)

    @staticmethod
    def build_mappings(
        world_path: Path,
        cache: dict,
        offline_mode: bool,
        manual_names: Optional[list],
        log: LogCallback,
        custom_mappings: Optional[Dict[str, str]] = None,
    ) -> list:
        """构建 UUID 映射列表

        根据世界存档、用户缓存等信息构建UUID映射列表。

        Args:
            world_path: 世界存档目录路径
            cache: 用户缓存数据字典
            offline_mode: 是否为离线模式
            manual_names: 手动指定的玩家名称列表
            log: 日志回调函数
            custom_mappings: 玩家名称到自定义 UUID 的映射

        Returns:
            list: UUID映射列表
        """
        return build_mappings(
            world_path,
            cache,
            offline_mode,
            manual_names,
            log,
            custom_mappings)
