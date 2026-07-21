"""
存档会话管理 (WorldSession)

实现非破坏性、延迟加载机制，支持任务队列与统一提交。
采用模块化设计，各功能拆分到独立模块。
"""
from pathlib import Path
from contextlib import nullcontext
from contextlib import AbstractContextManager
from typing import Dict, List, Optional, Tuple, Any, Callable, Union

from .models import WorldInfo
from .world_scanner import WorldScanner
from .nbt_loader import NbtLoader
from .player_manager import PlayerManager
from .action_queue import ActionQueue
from .action_executor import ActionExecutor
from ..region_utils import DimensionInfo
from ..types import LogCallback
from core.nbt import Compound
from core.world_index import WorldIndexSnapshot


class WorldSession:
    """存档会话管理器，提供延迟加载与任务队列（门面模式）。"""

    def __init__(
        self,
        world_path: Path,
        log: Optional[LogCallback] = None,
        write_lease_factory: Optional[
            Callable[[Path], AbstractContextManager[Any]]
        ] = None,
        backup_callback: Optional[Callable[[Path], Path]] = None,
        index_snapshot: Optional[WorldIndexSnapshot] = None,
        transaction_callback: Optional[
            Callable[[Path, Callable[[Path], None]], Any]
        ] = None,
    ) -> None:
        """初始化会话：扫描目录、加载 level.dat 并装配队列。

        Args:
            world_path: 源世界存档路径。
            log: 日志回调 ``(message, level)``。
            write_lease_factory: 可选写租约工厂，用于提交阶段互斥。
            backup_callback: 可选提交前备份钩子，返回备份路径。
            index_snapshot: 可选共享只读索引，避免重复目录扫描。
            transaction_callback: 可选统一世界事务提交端口。
        """
        self.world_path = world_path.resolve()
        self.log = log or (lambda msg, lvl="INFO": None)
        self._write_lease_factory = write_lease_factory
        self._backup_callback = backup_callback
        self._transaction_callback = transaction_callback

        self._scanner = WorldScanner(self.world_path, self.log)
        self._nbt_loader = NbtLoader(self.world_path, self.log)
        self._player_manager = PlayerManager(self.log)

        self._player_files: Dict[str, Path] = {}
        self._region_files: Dict[object, Path] = {}
        self._data_files: List[Path] = []

        from core.performance import get_tracker
        tracker = get_tracker()

        with tracker.track("存档加载", {"world": self.world_path.name}):
            if index_snapshot is None:
                scan_result = self._scanner.scan_all()
                self._player_files = scan_result["player_files"]
                self._region_files = scan_result["region_files"]
                self._data_files = scan_result["data_files"]
                usercache = scan_result["usercache"]
            else:
                self._validate_index_snapshot(index_snapshot)
                self._player_files = index_snapshot.player_file_map()
                self._region_files = {
                    key: value
                    for key, value in index_snapshot.region_file_map().items()
                }
                self._data_files = list(index_snapshot.data_files)
                usercache = index_snapshot.usercache_map()

            self._player_manager.initialize_names(
                self._player_files,
                usercache,
            )
            self._nbt_loader.load_level_info()
            self._action_queue = ActionQueue(
                self.world_path,
                self._player_files,
                self._region_files,
                self.log,
            )
            self._executor = ActionExecutor(
                self.world_path,
                self.log,
                backup_callback=self._backup_callback,
            )
            tracker.add_metadata("players", len(self._player_files))
            tracker.add_metadata("regions", len(self._region_files))

    # ════════════════════════════════════════════
    #  世界信息查询
    # ════════════════════════════════════════════

    def get_world_info(self) -> Optional[WorldInfo]:
        """返回已加载的世界信息"""
        return self._nbt_loader._world_info

    def get_dimensions(self) -> List[DimensionInfo]:
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

    def get_player_ender_items(self, uuid: str) -> List[Dict[str, Any]]:
        """提取指定玩家的末影箱物品列表"""
        data = self.get_player_data(uuid)
        return self._player_manager.get_player_ender_items(data)

    def get_player_file_path(self, uuid: str) -> Optional[Path]:
        """Return the absolute ``.dat`` path for a player UUID, if scanned."""
        norm = self._normalize_uuid(uuid)
        return self._player_files.get(norm)

    def seed_player_names(self, names: Dict[str, Optional[str]]) -> None:
        """Merge external UUID -> name mappings into the session name cache."""
        self._player_manager.seed_names(names)

    def get_known_player_name(self, uuid: str) -> Optional[str]:
        """Return a cached display name without loading player NBT."""
        return self._player_manager.get_known_name(uuid)

    def format_uuid_with_hyphens(self, uuid: str) -> str:
        """Public UUID formatting helper for UI layers."""
        return PlayerManager.format_uuid_with_hyphens(uuid)

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
        path = self._region_files.get((x, z))
        if path is None:
            path = self._region_files.get(f"region/r.{x}.{z}.mca")
        if path is None:
            self.log(f"区域文件不存在: r.{x}.{z}.mca", "WARNING")
            return None
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

    def queue_delete_region(
        self,
        x: int,
        z: int,
        region_path: Optional[Path] = None,
    ) -> None:
        """队列化删除指定区域文件的操作"""
        self._action_queue.queue_delete_region(x, z, region_path)

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
        target = (dest_path or self.world_path).resolve()
        if (
            self._transaction_callback is not None
            and actions
            and target == self.world_path
        ):
            try:
                self._transaction_callback(
                    target,
                    lambda staged: self._executor.apply_actions(
                        actions,
                        staged,
                    ),
                )
                self._action_queue.clear_queue()
                return True
            except Exception as exc:
                self.log(f"存档事务提交失败: {exc}", "ERROR")
                return False
        lease = (
            self._write_lease_factory(target)
            if self._write_lease_factory
            else nullcontext()
        )
        try:
            with lease:
                success = self._executor.execute_all(actions, dest_path, backup)
        except Exception as exc:
            self.log(f"存档写操作冲突: {exc}", "ERROR")
            return False

        if success:
            self._action_queue.clear_queue()

        return success

    def spawn(self) -> "WorldSession":
        """Reload this world while preserving application write dependencies."""
        return WorldSession(
            self.world_path,
            log=self.log,
            write_lease_factory=self._write_lease_factory,
            backup_callback=self._backup_callback,
            transaction_callback=self._transaction_callback,
        )

    def _validate_index_snapshot(
        self,
        snapshot: WorldIndexSnapshot,
    ) -> None:
        """拒绝把其他世界的索引错误注入当前会话。"""
        if snapshot.world_path != self.world_path:
            raise ValueError(
                f"世界索引路径不匹配: {snapshot.world_path} != {self.world_path}"
            )

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
