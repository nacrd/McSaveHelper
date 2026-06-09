"""
ActionQueue - 操作队列管理器
负责队列化各种操作（NBT 修改、区块编辑、文件删除等）
"""
from pathlib import Path
from typing import List, Union, Any, Callable, Optional, Dict
from .models import Action, ChunkTarget


class ActionQueue:
    """操作队列管理器"""

    def __init__(self, world_path: Path, player_files: Dict[str, Path],
                 region_files: Dict[tuple, Path], log_callback: Optional[Callable] = None):
        self.world_path = world_path
        self._player_files = player_files
        self._region_files = region_files
        self._log = log_callback or (lambda msg, lvl="INFO": None)
        self._action_queue: List[Action] = []

    def queue_modify_nbt(
        self,
        target: Union[Path, str],
        key_path: List[Union[str, int]],
        value: Any,
        operation: str = "set",
    ) -> None:
        """队列化一个 NBT 修改操作

        Args:
            target: 目标文件路径或玩家 UUID
            key_path: 键路径列表，例如 ["Data", "Player", "Health"]
            value: 新值（必须是 NBT 兼容类型）
            operation: 操作类型 (set/add/delete)
        """
        # 解析 target（字符串可能是 UUID 或路径）
        if isinstance(target, str) and (target.endswith(".dat") or "/" in target or "\\" in target):
            target = Path(target)
        elif isinstance(target, str):
            # 假设是 UUID
            norm_target = self._normalize_uuid(target)
            target_path = self._player_files.get(norm_target)
            if target_path is None:
                self._log(f"无法找到玩家 {target} 的文件", "ERROR")
                return
            target = target_path

        # 转换为相对路径
        if isinstance(target, Path) and target.is_absolute():
            try:
                target = target.relative_to(self.world_path)
            except ValueError:
                pass

        action = Action(
            type='modify_nbt',
            target=target,
            data={'key_path': key_path, 'value': value, 'operation': operation},
        )
        self._action_queue.append(action)
        self._log(f"已队列化 NBT {operation}: {key_path} -> {value}", "QUEUE")

    def queue_modify_json(
        self,
        target: Union[Path, str],
        key_path: List[Union[str, int]],
        value: Any,
        operation: str = "set",
    ) -> None:
        """队列化一个 JSON 修改操作

        Args:
            target: 目标文件路径
            key_path: 键路径列表
            value: 新值
            operation: 操作类型 (set/add/delete)
        """
        if isinstance(target, str):
            target = Path(target)

        if isinstance(target, Path) and target.is_absolute():
            try:
                target = target.relative_to(self.world_path)
            except ValueError:
                pass

        action = Action(
            type='modify_json',
            target=target,
            data={'key_path': key_path, 'value': value, 'operation': operation},
        )
        self._action_queue.append(action)
        self._log(f"已队列化 JSON {operation}: {key_path} -> {value}", "QUEUE")

    def queue_delete_region(self, x: int, z: int) -> None:
        """队列化删除指定区域文件的操作

        Args:
            x, z: 区域坐标
        """
        if (x, z) not in self._region_files:
            self._log(f"区域文件不存在: r.{x}.{z}.mca", "WARNING")
            return

        action = Action(
            type='delete_region',
            target=(x, z),
        )
        self._action_queue.append(action)
        self._log(f"已队列化删除区域: r.{x}.{z}.mca", "QUEUE")

    def queue_rename_player(self, old_uuid: str, new_uuid: str) -> None:
        """队列化重命名玩家文件的操作

        Args:
            old_uuid: 旧 UUID
            new_uuid: 新 UUID
        """
        if old_uuid not in self._player_files:
            self._log(f"玩家文件不存在: {old_uuid}", "WARNING")
            return

        action = Action(
            type='rename_player',
            target=(old_uuid, new_uuid),
        )
        self._action_queue.append(action)
        self._log(f"已队列化重命名玩家: {old_uuid} -> {new_uuid}", "QUEUE")

    def queue_custom(self, callback: Callable[[Path], Any]) -> None:
        """队列化一个自定义操作

        Args:
            callback: 接受目标路径的回调函数
        """
        action = Action(
            type='custom',
            target=None,
            callback=callback,
        )
        self._action_queue.append(action)
        self._log("已队列化自定义操作", "QUEUE")

    def queue_conversion(self, target_platform: str = "java", target_version: Optional[int] = None) -> None:
        """队列化一个存档转换操作

        Args:
            target_platform: 目标平台，"java" 或 "bedrock"
            target_version: 目标版本 ID（仅 Java 版有效）
        """
        def conversion_callback(target_world: Path) -> None:
            try:
                from ..converter import convert_world
                success = convert_world(
                    src_path=target_world,
                    dst_path=target_world,  # 原地转换
                    target_platform=target_platform,
                    target_version=target_version
                )
                if success:
                    self._log(f"存档转换成功 (平台: {target_platform}, 版本: {target_version})", "SUCCESS")
                else:
                    self._log("存档转换失败", "ERROR")
            except Exception as e:
                self._log(f"转换过程发生错误: {e}", "ERROR")

        self.queue_custom(conversion_callback)
        self._log(f"已队列化转换操作到平台 {target_platform}", "QUEUE")

    def queue_modify_chunk(self, region_path: Path, chunk_x: int, chunk_z: int,
                          full_chunk_data: Any) -> None:
        """队列化区块修改操作

        Args:
            region_path: 相对存档根目录的区域文件路径
            chunk_x: 区块在区域内的 X 坐标 (0-31)
            chunk_z: 区块在区域内的 Z 坐标 (0-31)
            full_chunk_data: 修改后的完整区块 NBT 数据
        """
        target = ChunkTarget(
            region_path=region_path,
            chunk_x=chunk_x,
            chunk_z=chunk_z,
            full_chunk_data=full_chunk_data
        )
        action = Action(
            type="modify_chunk",
            target=target,
            data=None
        )
        self._action_queue.append(action)
        self._log(f"已队列化区块修改: {region_path} [{chunk_x}, {chunk_z}]", "QUEUE")

    def get_queue(self) -> List[Action]:
        """获取当前队列"""
        return self._action_queue

    def get_queue_size(self) -> int:
        """返回队列中待执行的操作数量"""
        return len(self._action_queue)

    def clear_queue(self) -> None:
        """清空操作队列"""
        self._action_queue.clear()
        self._log("操作队列已清空", "QUEUE")

    @staticmethod
    def _normalize_uuid(uuid: str) -> str:
        """规范化 UUID：移除连字符并转为小写"""
        return uuid.replace("-", "").lower()
