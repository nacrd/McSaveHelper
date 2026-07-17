"""
ActionExecutor - 操作执行器
负责执行队列中的所有操作并写入目标存档
"""
import json
import shutil
from pathlib import Path
from typing import List, Union, Any, Optional, Callable
import nbtlib
from .models import Action, ChunkTarget
from ..utils import replace_directory_tree
from ..perf_timing import PerfTimer


class ActionExecutor:
    """操作执行器"""

    def __init__(self, world_path: Path, log_callback: Optional[Callable] = None):
        self.world_path = world_path
        self._log = log_callback or (lambda msg, lvl="INFO": None)

    def execute_all(
        self,
        actions: List[Action],
        dest_path: Optional[Path] = None,
        backup: bool = True,
    ) -> bool:
        """执行所有队列中的操作，并将结果写入目标路径

        Args:
            actions: 操作列表
            dest_path: 目标存档路径，若为 None 则原地修改（强烈不建议）
            backup: 是否在修改前备份原存档

        Returns:
            成功返回 True，失败返回 False
        """
        if dest_path is None:
            self._log("警告：未提供目标路径，将原地修改（风险极高）", "WARNING")
            dest_path = self.world_path
        else:
            dest_path = dest_path.resolve()

        # 1. 备份
        if backup and dest_path == self.world_path:
            backup_dir = self.world_path.parent / f"{self.world_path.name}.backup"
            try:
                if backup_dir.exists():
                    shutil.rmtree(backup_dir)
                with PerfTimer("action_executor.backup"):
                    shutil.copytree(self.world_path, backup_dir)
                self._log(f"已备份原存档到 {backup_dir}", "BACKUP")
            except Exception as e:
                self._log(f"备份失败: {e}", "ERROR")
                return False

        # 2. 克隆（如果目标路径与源路径不同）
        if dest_path != self.world_path:
            try:
                with PerfTimer("action_executor.clone"):
                    replace_directory_tree(self.world_path, dest_path)
                self._log(f"已克隆存档到 {dest_path}", "CLONE")
            except Exception as e:
                self._log(f"克隆失败: {e}", "ERROR")
                return False
            target_world = dest_path
        else:
            target_world = self.world_path

        # 3. 执行队列中的操作
        success = True
        with PerfTimer("action_executor.execute_queue"):
            for idx, action in enumerate(actions):
                try:
                    self._execute_action(action, target_world)
                    self._log(f"操作 {idx + 1}/{len(actions)} 执行成功", "ACTION")
                except Exception as e:
                    self._log(f"操作 {idx + 1} 执行失败: {e}", "ERROR")
                    success = False

        if success:
            self._log("所有操作已提交", "COMMIT")
        else:
            self._log("部分操作失败", "ERROR")

        return success

    def _execute_action(self, action: Action, target_world: Path) -> None:
        """执行单个操作"""
        if action.type == 'modify_nbt':
            self._execute_modify_nbt(action, target_world)
        elif action.type == 'modify_json':
            self._execute_modify_json(action, target_world)
        elif action.type == 'modify_chunk':
            self._execute_modify_chunk(action, target_world)
        elif action.type == 'delete_region':
            self._execute_delete_region(action, target_world)
        elif action.type == 'rename_player':
            self._execute_rename_player(action, target_world)
        elif action.type == 'custom' and action.callback:
            action.callback(target_world)
        else:
            raise ValueError(f"未知操作类型: {action.type}")

    def _execute_modify_nbt(self, action: Action, target_world: Path) -> None:
        """执行 NBT 修改"""
        target_path = action.target

        if isinstance(target_path, str):
            # 玩家 UUID，需要转换为实际路径
            target_path = target_world / "playerdata" / f"{target_path}.dat"
        elif isinstance(target_path, Path):
            # 确保路径相对于目标世界
            if not target_path.is_absolute():
                target_path = target_world / target_path
        else:
            target_path = Path(target_path)

        target_path = target_path.resolve()
        target_root = target_world.resolve()

        try:
            target_path.relative_to(target_root)
        except ValueError as exc:
            raise ValueError(f"拒绝修改存档目录外的 NBT 文件: {target_path}") from exc

        key_path = action.data['key_path']
        value = action.data['value']
        operation = action.data.get('operation', 'set')

        # 加载 NBT
        data = nbtlib.load(target_path)
        self._apply_path_operation(data, key_path, value, operation, f"NBT 文件 {target_path}")
        # 保存
        data.save()

    def _execute_modify_json(self, action: Action, target_world: Path) -> None:
        """执行 JSON 修改"""
        target_path = self._resolve_world_file(action.target, target_world)
        key_path = action.data['key_path']
        value = action.data['value']
        operation = action.data.get('operation', 'set')

        with open(target_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self._apply_path_operation(data, key_path, value, operation, f"JSON 文件 {target_path}")

        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _execute_modify_chunk(self, action: Action, target_world: Path) -> None:
        """执行区块修改操作"""
        target = action.target
        if not isinstance(target, ChunkTarget):
            raise ValueError("无效的区块目标")

        abs_region_path = target_world / target.region_path
        if not abs_region_path.exists():
            raise ValueError(f"区域文件不存在: {target.region_path}")

        self._write_chunk(
            abs_region_path,
            target.chunk_x,
            target.chunk_z,
            target.full_chunk_data,
        )
        self._log(f"已写回区块: {target.region_path} [{target.chunk_x}, {target.chunk_z}]", "SAVE")

    def _execute_delete_region(self, action: Action, target_world: Path) -> None:
        """删除区域文件"""
        x, z = action.target

        # 只删除标准 region 目录下的文件
        region_file = target_world / "region" / f"r.{x}.{z}.mca"
        if region_file.exists():
            region_file.unlink(missing_ok=True)

        # 同时删除 DIM* 下的区域文件
        for dim in target_world.glob("DIM*"):
            region_file = dim / "region" / f"r.{x}.{z}.mca"
            if region_file.exists():
                region_file.unlink(missing_ok=True)

    def _execute_rename_player(self, action: Action, target_world: Path) -> None:
        """重命名玩家文件"""
        old_uuid, new_uuid = action.target

        for folder in ["playerdata", "stats", "advancements"]:
            folder_path = target_world / folder
            if not folder_path.exists():
                continue

            for old_file in folder_path.glob(f"{old_uuid}*"):
                # 使用精确匹配替换，避免误替换
                suffix = old_file.name[len(old_uuid):]
                new_name = f"{new_uuid}{suffix}"
                new_path = folder_path / new_name

                if new_path.exists():
                    self._log(f"跳过玩家文件重命名冲突: {old_file.name} -> {new_name}", "WARN")
                    continue

                old_file.rename(new_path)

    def _resolve_world_file(self, target: Any, target_world: Path) -> Path:
        """解析世界文件路径（确保在存档目录内）"""
        target_path = target
        if isinstance(target_path, str):
            target_path = Path(target_path)
        elif not isinstance(target_path, Path):
            target_path = Path(target_path)

        if not target_path.is_absolute():
            target_path = target_world / target_path

        target_path = target_path.resolve()
        target_root = target_world.resolve()

        try:
            target_path.relative_to(target_root)
        except ValueError as exc:
            raise ValueError(f"拒绝修改存档目录外的文件: {target_path}") from exc

        return target_path

    def _apply_path_operation(
        self,
        data: Any,
        key_path: List[Union[str, int]],
        value: Any,
        operation: str,
        context: str,
    ) -> None:
        """应用路径操作（set/add/delete）到数据结构"""
        if not key_path:
            raise KeyError(f"{context} 的路径不能为空")

        # 导航到父节点
        node = data
        for key in key_path[:-1]:
            if isinstance(key, int) and isinstance(node, list) and 0 <= key < len(node):
                node = node[key]
            elif isinstance(key, str) and isinstance(node, dict) and key in node:
                node = node[key]
            else:
                raise KeyError(f"路径 {key_path} 不存在于 {context}")

        last_key = key_path[-1]
        if isinstance(last_key, int) and isinstance(node, list):
            self._apply_list_operation(node, last_key, value, operation)
            return
        if isinstance(last_key, str) and isinstance(node, dict):
            self._apply_mapping_operation(node, last_key, value, operation)
            return
        raise KeyError(f"路径 {key_path} 无法应用到 {context}")

    @staticmethod
    def _apply_list_operation(
        node: list,
        index: int,
        value: Any,
        operation: str,
    ) -> None:
        if operation == "add":
            if index < 0 or index > len(node):
                raise IndexError(f"列表插入位置越界: {index}")
            node.insert(index, value)
            return
        if index < 0 or index >= len(node):
            raise IndexError(f"列表操作位置越界: {index}")
        if operation == "delete":
            del node[index]
        else:
            node[index] = value

    @staticmethod
    def _apply_mapping_operation(
        node: dict,
        key: str,
        value: Any,
        operation: str,
    ) -> None:
        if operation == "add":
            if key in node:
                raise KeyError(f"字段已存在: {key}")
            node[key] = value
            return
        if key not in node:
            raise KeyError(f"字段不存在: {key}")
        if operation == "delete":
            del node[key]
        else:
            node[key] = value

    def _write_chunk(
        self,
        region_path: Path,
        chunk_x: int,
        chunk_z: int,
        chunk_data: Any,
    ) -> None:
        """Serialize legacy or nbtlib chunk data and write it atomically."""
        import io
        import zlib

        from core.mca import write_chunk_record

        buffer = io.BytesIO()
        if hasattr(chunk_data, "write_file"):
            chunk_data.write_file(buffer=buffer)
        elif hasattr(chunk_data, "write"):
            chunk_data.write(buffer)
        elif hasattr(chunk_data, "save"):
            chunk_data.save(buffer, gzipped=False)
        else:
            raise TypeError(
                f"不支持的区块 NBT 对象类型: {type(chunk_data).__name__}"
            )

        compressed = zlib.compress(buffer.getvalue(), 6)
        length = len(compressed) + 1
        record = length.to_bytes(4, "big") + b"\x02" + compressed
        write_chunk_record(
            region_path,
            (chunk_x, chunk_z),
            record,
            backup=True,
        )
