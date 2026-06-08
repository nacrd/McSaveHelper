"""区块编辑服务 - 处理区块重置和删除操作"""
import threading
import shutil
import struct
import time
from pathlib import Path
from typing import List, Optional, Tuple
from dataclasses import dataclass

from core.region_utils import parse_region_coords
from core.types import LogCallback


def _default_log(msg: str, lvl: str = "INFO") -> None:
    pass


@dataclass
class RegionInfo:
    """区域文件信息"""
    x: int
    z: int
    path: Path
    size: int
    chunk_count: int = 0


@dataclass
class ChunkInfo:
    """区块信息"""
    x: int
    z: int
    has_data: bool = False
    timestamp: int = 0


class RegionEditorService:
    """区块编辑服务"""

    def __init__(self, log: Optional[LogCallback] = None) -> None:
        self.log: LogCallback = log or _default_log

    def _log(self, message: str, level: str = "INFO") -> None:
        self.log(message, level)

    def get_region_info(self, region_path: Path) -> Optional[RegionInfo]:
        """获取区域文件信息"""
        if not region_path.exists():
            return None
        try:
            coords = parse_region_coords(region_path)
            if coords is None:
                raise ValueError(f"无效的区域文件名: {region_path.name}")
            x, z = coords
            size = region_path.stat().st_size
            chunk_count = self._count_chunks(region_path)
            return RegionInfo(
                x=x,
                z=z,
                path=region_path,
                size=size,
                chunk_count=chunk_count)
        except Exception as e:
            self._log(f"获取区域信息失败: {e}", "ERROR")
            return None

    def get_chunks_in_region(self, region_path: Path) -> List[ChunkInfo]:
        """获取区域文件中所有区块信息"""
        import anvil
        chunks = []
        try:
            region = anvil.Region.from_file(str(region_path))
            for x in range(32):
                for z in range(32):
                    try:
                        chunk = region.get_chunk(x, z)
                        has_data = chunk is not None
                        chunks.append(ChunkInfo(x=x, z=z, has_data=has_data))
                    except Exception:
                        chunks.append(ChunkInfo(x=x, z=z, has_data=False))
        except Exception as e:
            self._log(f"读取区块信息失败: {e}", "ERROR")
        return chunks

    def delete_region(self, region_path: Path, backup: bool = True) -> bool:
        """删除区域文件"""
        if not region_path.exists():
            self._log(f"区域文件不存在: {region_path.name}", "WARNING")
            return False
        try:
            if backup:
                backup_path = region_path.with_suffix(".mca.bak")
                shutil.copy2(region_path, backup_path)
                self._log(f"已备份区域文件: {backup_path.name}", "BACKUP")

            region_path.unlink()
            self._log(f"已删除区域文件: {region_path.name}", "DELETE")
            return True
        except Exception as e:
            self._log(f"删除区域文件失败: {e}", "ERROR")
            return False

    def reset_region(self, region_path: Path, backup: bool = True) -> bool:
        """重置区域文件（删除后让游戏重新生成）"""
        return self.delete_region(region_path, backup)

    def delete_chunks_in_region(self,
                                region_path: Path,
                                chunk_coords: List[Tuple[int,
                                                         int]],
                                backup: bool = True) -> Tuple[int,
                                                              int]:
        """删除区域文件中的指定区块

        Returns:
            (成功数, 失败数)
        """
        if not region_path.exists():
            self._log(f"区域文件不存在: {region_path.name}", "WARNING")
            return 0, len(chunk_coords)

        success = 0
        failed = 0

        try:
            self._backup_region(region_path, backup)
            with open(region_path, "r+b") as f:
                for cx, cz in chunk_coords:
                    if not 0 <= cx < 32 or not 0 <= cz < 32:
                        failed += 1
                        continue
                    index = self._chunk_index(cx, cz)
                    f.seek(index * 4)
                    f.write(b"\x00\x00\x00\x00")
                    f.seek(4096 + index * 4)
                    f.write(b"\x00\x00\x00\x00")
                    success += 1
            self._log(f"已从 {region_path.name} 重置 {success} 个区块", "SAVE")
        except Exception as e:
            self._log(f"操作区域文件失败: {e}", "ERROR")
            failed = len(chunk_coords) - success

        return success, failed

    def reset_chunk(
            self,
            world_path: Path,
            chunk_x: int,
            chunk_z: int,
            backup: bool = True) -> bool:
        region_path, local = self._resolve_chunk_path(
            world_path, chunk_x, chunk_z)
        success, failed = self.delete_chunks_in_region(
            region_path, [local], backup=backup)
        return success == 1 and failed == 0

    def copy_chunk(
        self,
        src_world: Path,
        dst_world: Path,
        src_chunk: Tuple[int, int],
        dst_chunk: Optional[Tuple[int, int]] = None,
        backup: bool = True,
    ) -> bool:
        """复制一个原始 MCA 区块记录到另一个存档。"""
        dst_chunk = dst_chunk or src_chunk
        src_region, src_local = self._resolve_chunk_path(
            src_world, src_chunk[0], src_chunk[1])
        dst_region, dst_local = self._resolve_chunk_path(
            dst_world, dst_chunk[0], dst_chunk[1])
        if not src_region.exists():
            self._log(f"源区域文件不存在: {src_region}", "WARNING")
            return False
        try:
            raw = self._read_chunk_record(
                src_region, src_local[0], src_local[1])
            if raw is None:
                self._log(f"源区块不存在: {src_chunk}", "WARNING")
                return False
            dst_region.parent.mkdir(parents=True, exist_ok=True)
            if not dst_region.exists():
                with open(dst_region, "wb") as f:
                    f.write(b"\x00" * 8192)
            self._backup_region(dst_region, backup)
            self._write_chunk_record(
                dst_region, dst_local[0], dst_local[1], raw)
            self._log(f"已复制区块 {src_chunk} -> {dst_chunk}", "SAVE")
            return True
        except Exception as e:
            self._log(f"复制区块失败: {e}", "ERROR")
            return False

    def delete_regions_batch(
            self, region_paths: List[Path], backup: bool = True) -> Tuple[int, int]:
        """批量删除区域文件

        Returns:
            (成功数, 失败数)
        """
        success = 0
        failed = 0

        for path in region_paths:
            if self.delete_region(path, backup):
                success += 1
            else:
                failed += 1

        return success, failed

    def delete_regions_by_coords(self,
                                 world_path: Path,
                                 coords: List[Tuple[int,
                                                    int]],
                                 backup: bool = True) -> Tuple[int,
                                                               int]:
        """按坐标删除区域文件

        Returns:
            (成功数, 失败数)
        """
        success = 0
        failed = 0

        region_dir = world_path / "region"
        if not region_dir.exists():
            self._log("region 目录不存在", "WARNING")
            return 0, len(coords)

        for x, z in coords:
            region_path = region_dir / f"r.{x}.{z}.mca"
            if self.delete_region(region_path, backup):
                success += 1
            else:
                failed += 1

        return success, failed

    def _count_chunks(self, region_path: Path) -> int:
        """计算区域文件中的区块数量"""
        import anvil
        try:
            region = anvil.Region.from_file(str(region_path))
            count = 0
            for x in range(32):
                for z in range(32):
                    try:
                        chunk = region.get_chunk(x, z)
                        if chunk is not None:
                            count += 1
                    except Exception:
                        pass
            return count
        except Exception:
            return 0

    def _backup_region(self, region_path: Path, backup: bool) -> None:
        if backup and region_path.exists():
            backup_path = region_path.with_suffix(".mca.bak")
            if not backup_path.exists():
                shutil.copy2(region_path, backup_path)
                self._log(f"已备份区域文件: {backup_path.name}", "BACKUP")

    def _chunk_index(self, cx: int, cz: int) -> int:
        return (cx & 31) + (cz & 31) * 32

    def _resolve_chunk_path(self, world_path: Path, chunk_x: int,
                            chunk_z: int) -> Tuple[Path, Tuple[int, int]]:
        rx = chunk_x // 32
        rz = chunk_z // 32
        return world_path / "region" / \
            f"r.{rx}.{rz}.mca", (chunk_x % 32, chunk_z % 32)

    def _read_chunk_record(
            self,
            region_path: Path,
            cx: int,
            cz: int) -> Optional[bytes]:
        with open(region_path, "rb") as f:
            index = self._chunk_index(cx, cz)
            f.seek(index * 4)
            loc = f.read(4)
            if len(loc) != 4 or loc == b"\x00\x00\x00\x00":
                return None
            offset = int.from_bytes(loc[:3], "big") * 4096
            sectors = loc[3]
            if offset <= 0 or sectors <= 0:
                return None
            f.seek(offset)
            return f.read(sectors * 4096)

    def _write_chunk_record(
            self,
            region_path: Path,
            cx: int,
            cz: int,
            raw: bytes) -> None:
        sectors = max(1, (len(raw) + 4095) // 4096)
        if sectors > 255:
            raise ValueError("区块数据超过 MCA 单条记录上限")
        padded = raw + (b"\x00" * (sectors * 4096 - len(raw)))
        with open(region_path, "r+b") as f:
            f.seek(0, 2)
            end = f.tell()
            if end < 8192:
                f.seek(0)
                f.write(b"\x00" * (8192 - end))
                end = 8192
            if end % 4096:
                pad = 4096 - (end % 4096)
                f.write(b"\x00" * pad)
                end += pad
            sector_offset = end // 4096
            f.write(padded)
            index = self._chunk_index(cx, cz)
            f.seek(index * 4)
            f.write(sector_offset.to_bytes(3, "big") + bytes([sectors]))
            f.seek(4096 + index * 4)
            f.write(struct.pack(">I", int(time.time())))


_region_editor_service: Optional[RegionEditorService] = None
_region_editor_service_lock = threading.Lock()


def get_region_editor_service(
        log: Optional[LogCallback] = None) -> RegionEditorService:
    """获取区块编辑服务单例（线程安全）"""
    global _region_editor_service
    with _region_editor_service_lock:
        if _region_editor_service is None:
            _region_editor_service = RegionEditorService(log=log)
        elif log is not None:
            _region_editor_service.log = log
    return _region_editor_service
