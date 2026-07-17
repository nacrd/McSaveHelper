"""
存档会话管理 (WorldSession)

实现非破坏性、延迟加载机制，支持任务队列与统一提交。
采用模块化设计，各功能拆分到独立模块。
"""
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Callable, Union

from .models import WorldInfo
from .world_scanner import WorldScanner
from .nbt_loader import NbtLoader
from .player_manager import PlayerManager
from .action_queue import ActionQueue
from .action_executor import ActionExecutor
from .backup_manager import BackupManager
from ..types import LogCallback
from nbtlib import Compound


class WorldSession:
    """存档会话管理器，提供延迟加载与任务队列（门面模式）"""

    def __init__(self, world_path: Path, log: Optional[LogCallback] = None) -> None:
        """初始化会话，仅读取基础信息并扫描目录结构

        Args:
            world_path: 源世界存档路径
            log: 日志回调函数，接受 (消息, 级别) 参数
        """
        self.world_path = world_path.resolve()
        self.log = log or (lambda msg, lvl="INFO": None)

        # 初始化各模块
        self._scanner = WorldScanner(self.world_path, self.log)
        self._nbt_loader = NbtLoader(self.world_path, self.log)
        self._player_manager = PlayerManager(self.log)
        self._backup_manager = BackupManager(self.world_path, self.log)

        # 存储扫描结果
        self._player_files: Dict[str, Path] = {}
        self._region_files: Dict[Tuple[int, int], Path] = {}
        self._data_files: List[Path] = []

        # 性能追踪
        from core.performance import get_tracker
        tracker = get_tracker()

        with tracker.track("存档加载", {"world": self.world_path.name}):
            # 扫描文件
            scan_result = self._scanner.scan_all()
            self._player_files = scan_result['player_files']
            self._region_files = scan_result['region_files']
            self._data_files = scan_result['data_files']
            usercache = scan_result['usercache']

            # 初始化玩家管理器
            self._player_manager.initialize_names(self._player_files, usercache)

            # 加载 level.dat
            self._nbt_loader.load_level_info()

            # 初始化操作队列
            self._action_queue = ActionQueue(
                self.world_path, self._player_files, self._region_files, self.log
            )

            # 初始化执行器
            self._executor = ActionExecutor(self.world_path, self.log)

            tracker.add_metadata("players", len(self._player_files))
            tracker.add_metadata("regions", len(self._region_files))

    # ════════════════════════════════════════════
    #  世界信息查询
    # ════════════════════════════════════════════

    def get_world_info(self) -> Optional[WorldInfo]:
        """返回已加载的世界信息"""
        return self._nbt_loader._world_info

    def get_dimensions(self) -> List[Dict[str, str]]:
        """扫描存档中所有可用的维度目录

        Returns:
            维度信息列表，每项包含 id, name, region_dir
        """
        return self._scanner.scan_dimensions(self._region_files)

    # ════════════════════════════════════════════
    #  玩家数据访问
    # ════════════════════════════════════════════

    def get_player_uuids(self) -> List[str]:
        """返回所有玩家的 UUID 列表"""
        return list(self._player_files.keys())

    def get_player_names(self) -> Dict[str, Optional[str]]:
        """返回 UUID 到玩家名称的映射

        仅返回已从 usercache.json 缓存的名称，不加载 NBT 文件。
        未知名称返回 None，可通过 resolve_player_name() 按需加载。
        """
        return self._player_manager.get_player_names(list(self._player_files.keys()))

    def resolve_player_name(self, uuid: str) -> Optional[str]:
        """按需解析单个玩家名称（加载 NBT）

        Args:
            uuid: 玩家 UUID

        Returns:
            玩家名称，若无法解析则返回 None
        """
        norm = self._normalize_uuid(uuid)
        data = self.get_player_data(norm)
        return self._player_manager.resolve_player_name(norm, data)

    def get_player_data(self, uuid: str) -> Optional[Compound]:
        """延迟加载指定 UUID 的玩家数据文件

        Args:
            uuid: 玩家 UUID（不带扩展名）

        Returns:
            玩家数据的 NBT 标签，若加载失败则返回 None
        """
        norm_uuid = self._normalize_uuid(uuid)
        return self._nbt_loader.load_player_data(norm_uuid, self._player_files)

    def get_player_inventory(self, uuid: str) -> List[Dict[str, Any]]:
        """提取指定玩家的背包物品列表

        Args:
            uuid: 玩家 UUID

        Returns:
            物品字典列表，每项包含 slot, id, count, tag
        """
        data = self.get_player_data(uuid)
        return self._player_manager.get_player_inventory(data)

    def load_player_data(self, uuid: str) -> Optional[Compound]:
        """加载指定玩家的完整 NBT 数据（供 ExplorerView 使用）"""
        return self.get_player_data(uuid)

    def load_player_nbt(self, uuid: str) -> Optional[Compound]:
        """加载指定玩家的完整 NBT 数据（供 NBT 查看器使用）"""
        return self.get_player_data(uuid)

    def import_usercache(self, path: Path) -> int:
        """从指定的 usercache.json 文件导入玩家名称映射

        Args:
            path: usercache.json 文件路径

        Returns:
            成功导入的条目数量
        """
        return self._player_manager.import_usercache(path, self._player_files)

    # ════════════════════════════════════════════
    #  区域和区块访问
    # ════════════════════════════════════════════

    def get_region(self, x: int, z: int) -> Optional[Path]:
        """获取指定坐标的区域文件路径

        Args:
            x, z: 区域坐标

        Returns:
            区域文件路径，若不存在则返回 None
        """
        if (x, z) not in self._region_files:
            self.log(f"区域文件不存在: r.{x}.{z}.mca", "WARNING")
            return None
        path = self._region_files[(x, z)]
        self._nbt_loader.cache_region(x, z, path)
        return path

    def load_chunk_nbt(
        self,
        region_path: Path,
        chunk_x: int,
        chunk_z: int,
    ) -> Optional[Tuple[Any, Path]]:
        """加载指定区块的 NBT 数据

        Args:
            region_path: 相对存档根目录的区域文件路径
            chunk_x: 区块在区域内的 X 坐标 (0-31)
            chunk_z: 区块在区域内的 Z 坐标 (0-31)

        Returns:
            (区块数据, 绝对路径) 或 None
        """
        return self._nbt_loader.load_chunk_nbt(region_path, chunk_x, chunk_z)

    # ════════════════════════════════════════════
    #  操作队列
    # ════════════════════════════════════════════

    def queue_modify_nbt(
        self,
        target: Union[Path, str],
        key_path: List[Union[str, int]],
        value: Any,
        operation: str = "set",
    ) -> None:
        """队列化一个 NBT 修改操作"""
        self._action_queue.queue_modify_nbt(target, key_path, value, operation)

    def queue_modify_json(
        self,
        target: Union[Path, str],
        key_path: List[Union[str, int]],
        value: Any,
        operation: str = "set",
    ) -> None:
        """队列化一个 JSON 修改操作"""
        self._action_queue.queue_modify_json(target, key_path, value, operation)

    def queue_delete_region(self, x: int, z: int) -> None:
        """队列化删除指定区域文件的操作"""
        self._action_queue.queue_delete_region(x, z)

    def queue_rename_player(self, old_uuid: str, new_uuid: str) -> None:
        """队列化重命名玩家文件的操作"""
        self._action_queue.queue_rename_player(old_uuid, new_uuid)

    def queue_custom(self, callback: Callable[[Path], Any]) -> None:
        """队列化一个自定义操作"""
        self._action_queue.queue_custom(callback)

    def queue_conversion(
        self,
        target_platform: str = "java",
        target_version: Optional[int] = None,
    ) -> None:
        """队列化一个存档转换操作"""
        self._action_queue.queue_conversion(target_platform, target_version)

    def queue_modify_chunk(
        self,
        region_path: Path,
        chunk_x: int,
        chunk_z: int,
        full_chunk_data: Any,
    ) -> None:
        """队列化区块修改操作"""
        self._action_queue.queue_modify_chunk(region_path, chunk_x, chunk_z, full_chunk_data)

    def get_queue_size(self) -> int:
        """返回队列中待执行的操作数量"""
        return self._action_queue.get_queue_size()

    def clear_queue(self) -> None:
        """清空操作队列"""
        self._action_queue.clear_queue()

    # ════════════════════════════════════════════
    #  提交和执行
    # ════════════════════════════════════════════

    def commit(self, dest_path: Optional[Path] = None, backup: bool = True) -> bool:
        """执行所有队列中的操作，并将结果写入目标路径

        Args:
            dest_path: 目标存档路径，若为 None 则原地修改（强烈不建议）
            backup: 是否在修改前备份原存档

        Returns:
            成功返回 True，失败返回 False
        """
        actions = self._action_queue.get_queue()
        success = self._executor.execute_all(actions, dest_path, backup)

        if success:
            self._action_queue.clear_queue()

        return success

    # ════════════════════════════════════════════
    #  备份和恢复
    # ════════════════════════════════════════════

    def create_backup(self, backup_name: Optional[str] = None) -> Optional[Path]:
        """创建当前存档的备份"""
        return self._backup_manager.create_backup(backup_name)

    def restore_backup(self, backup_path: Path, replace_current: bool = False) -> bool:
        """从备份恢复存档"""
        return self._backup_manager.restore_backup(backup_path, replace_current)

    def list_backups(self) -> List[Path]:
        """列出当前存档的所有备份"""
        return self._backup_manager.list_backups()

    # ════════════════════════════════════════════
    #  工具方法
    # ════════════════════════════════════════════

    @staticmethod
    def _normalize_uuid(uuid: str) -> str:
        """规范化 UUID：移除连字符并转为小写"""
        return PlayerManager.normalize_uuid(uuid)

    @staticmethod
    def _format_uuid_with_hyphens(uuid: str) -> str:
        """将规范化 UUID（32 字符）格式化为带连字符的标准形式"""
        return PlayerManager.format_uuid_with_hyphens(uuid)
