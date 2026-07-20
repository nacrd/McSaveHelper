"""基于原生 MCA 原语的高层区域编辑，无 UI 依赖。"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from core.mca.region_file import RegionFile, world_to_local
from core.mca.writer import copy_chunk_record, delete_chunk_entries
from core.region_utils import parse_region_coords
from core.types import LogCallback


def _discard_log(message: str, level: str = "INFO") -> None:
    del message, level


@dataclass(frozen=True)
class RegionInfo:
    """单个区域文件的摘要信息。"""

    x: int
    z: int
    path: Path
    size: int
    chunk_count: int = 0


@dataclass(frozen=True)
class ChunkInfo:
    """区域内局部区块的摘要（含是否有数据与时间戳）。"""

    x: int
    z: int
    has_data: bool = False
    timestamp: int = 0


class RegionEditor:
    """执行区域/区块级编辑，不依赖应用或 UI 层。"""

    def __init__(self, log: Optional[LogCallback] = None) -> None:
        """可选注入日志回调。

        Args:
            log: ``(message, level)`` 回调；默认丢弃。
        """
        self.log: LogCallback = log or _discard_log

    def _log(self, message: str, level: str = "INFO") -> None:
        self.log(message, level)

    def get_region_info(self, region_path: Path) -> Optional[RegionInfo]:
        """读取区域文件摘要。

        Args:
            region_path: ``r.X.Z.mca`` 路径。

        Returns:
            Optional[RegionInfo]: 成功时的摘要；文件缺失或损坏时为 None。
        """
        if not region_path.exists():
            return None
        try:
            coords = parse_region_coords(region_path)
            if coords is None:
                raise ValueError(f"无效的区域文件名: {region_path.name}")
            with RegionFile.open(region_path) as region:
                chunk_count = region.count_chunks()
            return RegionInfo(
                x=coords[0],
                z=coords[1],
                path=region_path,
                size=region_path.stat().st_size,
                chunk_count=chunk_count,
            )
        except (OSError, ValueError, TypeError, RuntimeError, KeyError) as exc:
            self._log(f"获取区域信息失败: {exc}", "ERROR")
            return None
        except Exception as exc:
            self._log(f"获取区域信息失败: {exc}", "ERROR")
            return None

    def get_chunks_in_region(self, region_path: Path) -> List[ChunkInfo]:
        """枚举区域内全部 32×32 局部槽的摘要。

        Args:
            region_path: 区域文件路径。

        Returns:
            List[ChunkInfo]: 1024 项（失败时可能更短或为空）。
        """
        chunks: List[ChunkInfo] = []
        try:
            with RegionFile.open(region_path) as region:
                present = set(region.iter_present_chunks())
                for x in range(32):
                    for z in range(32):
                        chunks.append(
                            ChunkInfo(
                                x=x,
                                z=z,
                                has_data=(x, z) in present,
                                timestamp=region.chunk_timestamp(x, z),
                            )
                        )
        except (OSError, ValueError, TypeError, RuntimeError, KeyError) as exc:
            self._log(f"读取区块信息失败: {exc}", "ERROR")
        except Exception as exc:
            self._log(f"读取区块信息失败: {exc}", "ERROR")
        return chunks

    def delete_region(self, region_path: Path, backup: bool = True) -> bool:
        """删除区域文件；可选先写 ``.bak``（已存在 bak 则不覆盖）。

        Args:
            region_path: 目标 .mca。
            backup: 是否备份。

        Returns:
            bool: 是否成功删除。
        """
        if not region_path.exists():
            self._log(f"区域文件不存在: {region_path.name}", "WARNING")
            return False
        try:
            if backup:
                backup_path = region_path.with_suffix(region_path.suffix + ".bak")
                if not backup_path.exists():
                    shutil.copy2(region_path, backup_path)
                    self._log(f"已备份区域文件: {backup_path.name}", "BACKUP")
            region_path.unlink()
            self._log(f"已删除区域文件: {region_path.name}", "DELETE")
            return True
        except OSError as exc:
            self._log(f"删除区域文件失败: {exc}", "ERROR")
            return False

    def reset_region(self, region_path: Path, backup: bool = True) -> bool:
        """重置区域：当前实现为删除整个区域文件。

        Args:
            region_path: 目标 .mca。
            backup: 是否备份。

        Returns:
            bool: 是否成功。
        """
        return self.delete_region(region_path, backup)

    def delete_chunks_in_region(
        self,
        region_path: Path,
        chunk_coords: List[Tuple[int, int]],
        backup: bool = True,
    ) -> Tuple[int, int]:
        """清除区域内指定局部区块的位置表项。

        Args:
            region_path: 区域文件。
            chunk_coords: 局部 ``(cx, cz)`` 列表。
            backup: 是否备份。

        Returns:
            Tuple[int, int]: ``(成功数, 失败数)``。
        """
        if not region_path.exists():
            self._log(f"区域文件不存在: {region_path.name}", "WARNING")
            return 0, len(chunk_coords)
        valid = [
            (chunk_x, chunk_z)
            for chunk_x, chunk_z in chunk_coords
            if 0 <= chunk_x < 32 and 0 <= chunk_z < 32
        ]
        try:
            success = delete_chunk_entries(region_path, valid, backup=backup)
            failed = len(chunk_coords) - success
            self._log(f"已从 {region_path.name} 重置 {success} 个区块", "SAVE")
            return success, failed
        except (OSError, ValueError, TypeError, RuntimeError, KeyError) as exc:
            self._log(f"操作区域文件失败: {exc}", "ERROR")
            return 0, len(chunk_coords)
        except Exception as exc:
            self._log(f"操作区域文件失败: {exc}", "ERROR")
            return 0, len(chunk_coords)

    def reset_chunk(
        self,
        world_path: Path,
        chunk_x: int,
        chunk_z: int,
        backup: bool = True,
    ) -> bool:
        """按世界 chunk 坐标重置单个区块（清位置表）。

        Args:
            world_path: 世界根目录（含 region/）。
            chunk_x: 世界 chunk X。
            chunk_z: 世界 chunk Z。
            backup: 是否备份。

        Returns:
            bool: 是否恰好清除成功一项。
        """
        region_path, local_coords = self._resolve_chunk_path(
            world_path, chunk_x, chunk_z
        )
        success, failed = self.delete_chunks_in_region(
            region_path, [local_coords], backup=backup
        )
        return success == 1 and failed == 0

    def copy_chunk(
        self,
        source_world: Path,
        destination_world: Path,
        source_chunk: Tuple[int, int],
        destination_chunk: Optional[Tuple[int, int]] = None,
        backup: bool = True,
    ) -> bool:
        """在世界间复制压缩区块记录（不重解析 NBT）。

        Args:
            source_world: 源世界路径。
            destination_world: 目标世界路径。
            source_chunk: 源世界 chunk 坐标。
            destination_chunk: 目标 chunk；默认与源相同。
            backup: 是否备份目标区域。

        Returns:
            bool: 是否复制成功。
        """
        destination_chunk = destination_chunk or source_chunk
        source_region, source_local = self._resolve_chunk_path(
            source_world, *source_chunk
        )
        destination_region, destination_local = self._resolve_chunk_path(
            destination_world, *destination_chunk
        )
        if not source_region.exists():
            self._log(f"源区域文件不存在: {source_region}", "WARNING")
            return False
        try:
            copy_chunk_record(
                source_region,
                source_local,
                destination_region,
                destination_local,
                backup=backup,
            )
            self._log(f"已复制区块 {source_chunk} -> {destination_chunk}", "SAVE")
            return True
        except (OSError, ValueError, TypeError, RuntimeError, KeyError) as exc:
            self._log(f"复制区块失败: {exc}", "ERROR")
            return False
        except Exception as exc:
            self._log(f"复制区块失败: {exc}", "ERROR")
            return False

    def delete_regions_batch(
        self, region_paths: List[Path], backup: bool = True
    ) -> Tuple[int, int]:
        """批量删除区域文件。

        Args:
            region_paths: 路径列表。
            backup: 是否备份。

        Returns:
            Tuple[int, int]: ``(成功数, 失败数)``。
        """
        success = sum(self.delete_region(path, backup) for path in region_paths)
        return success, len(region_paths) - success

    def delete_regions_by_coords(
        self,
        world_path: Path,
        coords: List[Tuple[int, int]],
        backup: bool = True,
    ) -> Tuple[int, int]:
        """按区域坐标批量删除 ``world/region/r.X.Z.mca``。

        Args:
            world_path: 世界根目录。
            coords: ``(rx, rz)`` 列表。
            backup: 是否备份。

        Returns:
            Tuple[int, int]: ``(成功数, 失败数)``。
        """
        region_dir = world_path / "region"
        if not region_dir.exists():
            self._log("region 目录不存在", "WARNING")
            return 0, len(coords)
        paths = [region_dir / f"r.{x}.{z}.mca" for x, z in coords]
        return self.delete_regions_batch(paths, backup)

    @staticmethod
    def _resolve_chunk_path(
        world_path: Path, chunk_x: int, chunk_z: int
    ) -> Tuple[Path, Tuple[int, int]]:
        region_x, region_z, local_x, local_z = world_to_local(chunk_x, chunk_z)
        return (
            world_path / "region" / f"r.{region_x}.{region_z}.mca",
            (local_x, local_z),
        )
