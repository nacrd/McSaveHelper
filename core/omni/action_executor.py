"""
ActionExecutor - 操作执行器
负责执行队列中的所有操作并写入目标存档
"""
import json
import shutil
import tempfile
from pathlib import Path
from typing import List, Union, Any, Optional, Callable
import core.nbt as nbtlib
from .models import Action, ChunkTarget
from ..utils import (
    find_advancements_dirs,
    find_player_data_dirs,
    find_stats_dirs,
    get_write_player_data_dir,
    publish_directory_tree,
)
from ..perf_timing import PerfTimer
from core.uuid_utils import normalize_uuid


class ActionExecutor:
    """操作执行器"""

    def __init__(
        self,
        world_path: Path,
        log_callback: Optional[Callable] = None,
        backup_callback: Optional[Callable[[Path], Path]] = None,
    ) -> None:
        """绑定目标世界与可选日志/备份钩子。

        Args:
            world_path: 源世界路径（执行前应已通过写租约/存在性校验）。
            log_callback: ``(message, level)`` 日志回调。
            backup_callback: 写前备份钩子，接收世界路径并返回备份路径。
        """
        self.world_path = world_path
        self._log = log_callback or (lambda msg, lvl="INFO": None)
        self._backup_callback = backup_callback

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
        target_world = (dest_path or self.world_path).resolve()
        if not actions:
            self._log("没有需要提交的操作", "INFO")
            return True
        try:
            if backup and target_world.exists():
                self._create_backup(target_world)
            return self._execute_transaction(actions, target_world)
        except (OSError, ValueError, TypeError, RuntimeError, KeyError) as exc:
            self._log(f"提交失败，原存档保持不变: {exc}", "ERROR")
            return False
        except Exception as exc:
            # Transaction boundary: never leave partial writes published.
            self._log(f"提交失败，原存档保持不变: {exc}", "ERROR")
            return False

    def apply_actions(
        self,
        actions: List[Action],
        prepared_world: Path,
    ) -> None:
        """把队列操作应用到调用方拥有的暂存世界。

        Args:
            actions: 已验证的操作列表。
            prepared_world: 世界事务创建的完整暂存副本。
        """
        with PerfTimer("action_executor.execute_queue"):
            for index, action in enumerate(actions):
                self._execute_action(action, prepared_world)
                self._log(
                    f"操作 {index + 1}/{len(actions)} 执行成功",
                    "ACTION",
                )

    def _create_backup(self, target_world: Path) -> None:
        if self._backup_callback:
            backup_path = self._backup_callback(target_world)
            self._log(f"已备份原存档到 {backup_path}", "BACKUP")
            return
        backup_dir = target_world.parent / f"{target_world.name}.backup"
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        with PerfTimer("action_executor.backup"):
            shutil.copytree(target_world, backup_dir)
        self._log(f"已备份原存档到 {backup_dir}", "BACKUP")

    def _execute_transaction(
        self,
        actions: List[Action],
        target_world: Path,
    ) -> bool:
        target_world.parent.mkdir(parents=True, exist_ok=True)
        staging_root = Path(tempfile.mkdtemp(
            prefix=f".mcsavehelper_commit_{target_world.name}_",
            dir=target_world.parent,
        ))
        prepared = staging_root / target_world.name
        try:
            with PerfTimer("action_executor.clone"):
                shutil.copytree(self.world_path, prepared)
            with PerfTimer("action_executor.execute_queue"):
                for index, action in enumerate(actions):
                    self._execute_action(action, prepared)
                    self._log(
                        f"操作 {index + 1}/{len(actions)} 执行成功",
                        "ACTION",
                    )
            publish_directory_tree(prepared, target_world)
            self._log("所有操作已原子提交", "COMMIT")
            return True
        finally:
            shutil.rmtree(staging_root, ignore_errors=True)

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
            # Bare UUID fallback: resolve under 26.1 or legacy playerdata.
            target_path = self._resolve_player_dat_path(target_world, target_path)
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
        self._apply_path_operation(
            data, key_path, value, operation, f"NBT 文件 {target_path}"
        )
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

        abs_region_path = self._resolve_world_file(
            target.region_path,
            target_world,
        )
        if abs_region_path.suffix.lower() != ".mca":
            raise ValueError(f"区块目标不是 MCA 文件: {target.region_path}")
        if not 0 <= target.chunk_x < 32 or not 0 <= target.chunk_z < 32:
            raise ValueError("区块局部坐标必须位于 0-31")
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
        region_file = self._resolve_world_file(action.target, target_world)
        if region_file.suffix.lower() != ".mca":
            raise ValueError(f"区域删除目标不是 MCA 文件: {action.target}")
        if not region_file.exists():
            raise FileNotFoundError(f"区域文件不存在: {action.target}")
        region_file.unlink()

    def _execute_rename_player(self, action: Action, target_world: Path) -> None:
        """重命名玩家文件（兼容 26.1 players/* 与 legacy 路径）"""
        old_uuid, new_uuid = action.target
        old_norm = normalize_uuid(str(old_uuid))
        new_norm = normalize_uuid(str(new_uuid))
        if not old_norm or not new_norm:
            self._log(f"无效的玩家 UUID 重命名: {old_uuid} -> {new_uuid}", "ERROR")
            return

        folders: list[Path] = []
        for finder in (
            find_player_data_dirs,
            find_stats_dirs,
            find_advancements_dirs,
        ):
            for folder_path in finder(target_world):
                if folder_path.is_dir() and folder_path not in folders:
                    folders.append(folder_path)

        for folder_path in folders:
            for old_file in folder_path.glob(f"{old_norm}*"):
                # Prefer exact stem match (uuid.dat / uuid.json)
                stem = old_file.stem
                if normalize_uuid(stem) != old_norm and not stem.startswith(
                    old_norm
                ):
                    continue
                suffix = old_file.name[len(old_norm):]
                if not suffix.startswith("."):
                    # Defensive: only rename files whose name is uuid + extension
                    if not old_file.name.startswith(old_norm):
                        continue
                    suffix = old_file.name[len(old_norm):]
                new_name = f"{new_norm}{suffix}"
                new_path = folder_path / new_name

                if new_path.exists():
                    self._log(
                        f"跳过玩家文件重命名冲突: {old_file.name} -> {new_name}",
                        "WARN",
                    )
                    continue

                old_file.rename(new_path)

    @staticmethod
    def _resolve_player_dat_path(target_world: Path, uuid_value: str) -> Path:
        """Locate or default a player ``.dat`` path for a bare UUID string."""
        norm = normalize_uuid(uuid_value)
        for player_dir in find_player_data_dirs(target_world):
            if not player_dir.is_dir():
                continue
            candidate = player_dir / f"{norm}.dat"
            if candidate.is_file():
                return candidate
            # Also accept original casing/hyphen file names
            for path in player_dir.glob("*.dat"):
                if normalize_uuid(path.stem) == norm:
                    return path
        # Default write location when creating/missing
        return get_write_player_data_dir(target_world) / f"{norm}.dat"

    def _resolve_world_file(self, target: Any, target_world: Path) -> Path:
        """解析世界文件路径（确保在存档目录内）"""
        target_path = target
        if isinstance(target_path, str):
            target_path = Path(target_path)
        elif not isinstance(target_path, Path):
            target_path = Path(target_path)

        if target_path.is_absolute():
            try:
                relative = target_path.resolve().relative_to(
                    self.world_path.resolve()
                )
                target_path = target_world / relative
            except ValueError:
                pass
        else:
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
        """Serialize chunk NBT data and write it atomically."""
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
