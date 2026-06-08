"""
存档区域地图后台扫描服务 (HeatmapService)

提供异步、非阻塞的区域文件扫描能力，
支持进度追踪和数据查询。
"""
import asyncio
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Tuple, Optional
from dataclasses import dataclass

from core.region_utils import parse_region_coords, scan_region_dir


@dataclass
class ScanProgress:
    """扫描进度信息"""
    total_files: int = 0
    scanned_files: int = 0
    progress: float = 0.0  # 0.0 到 1.0
    is_scanning: bool = False
    error: Optional[str] = None


class HeatmapService:
    """
    存档区域地图后台扫描服务（单例模式）
    
    职责：
    - 异步扫描 Minecraft region 目录
    - 缓存区域文件大小数据
    - 提供进度查询接口
    """
    
    _instance: Optional['HeatmapService'] = None

    def __new__(cls) -> 'HeatmapService':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance
    
    def _init(self) -> None:
        """初始化内部状态"""
        self._mca_data: Dict[Tuple[int, int], int] = {}
        self._region_meta: Dict[Tuple[int, int], Dict[str, Any]] = {}
        self._is_scanning: bool = False
        self._scan_progress: float = 0.0
        self._scan_task: Optional[asyncio.Task] = None
        self._scanned_count: int = 0
        self._total_count: int = 0
        self._error: Optional[str] = None
    
    @property
    def is_scanning(self) -> bool:
        """当前是否正在扫描"""
        return self._is_scanning
    
    @property
    def scan_progress(self) -> float:
        """扫描进度 (0.0 到 1.0)"""
        return self._scan_progress
    
    @property
    def progress_info(self) -> ScanProgress:
        """获取完整的进度信息"""
        return ScanProgress(
            total_files=self._total_count,
            scanned_files=self._scanned_count,
            progress=self._scan_progress,
            is_scanning=self._is_scanning,
            error=self._error
        )
    
    def get_all_data(self) -> Dict[Tuple[int, int], int]:
        """
        获取当前已扫描到的完整数据快照
        
        Returns:
            Dict[Tuple[int, int], int]: 坐标到文件大小的映射
        """
        return self._mca_data.copy()

    def get_region_meta(self, coord: Tuple[int, int]) -> Dict[str, Any]:
        return dict(self._region_meta.get(coord, {}))

    def get_all_region_meta(self) -> Dict[Tuple[int, int], Dict[str, Any]]:
        return {coord: dict(meta) for coord, meta in self._region_meta.items()}
    
    def get_data_snapshot(self) -> Dict[Tuple[int, int], int]:
        """
        获取数据快照（get_all_data 的别名，保持兼容性）
        """
        return self.get_all_data()
    
    def clear_data(self) -> None:
        """清空所有缓存数据"""
        self._mca_data.clear()
        self._region_meta.clear()
        self._scanned_count = 0
        self._total_count = 0
        self._scan_progress = 0.0
        self._error = None
    
    async def start_silent_scan(self, region_dir: str, batch_size: int = 30) -> None:
        """
        启动静默扫描任务
        
        Args:
            region_dir: region 目录路径
            batch_size: 每批处理文件数量（用于进度更新）
        """
        # 如果正在扫描，先取消
        if self._is_scanning:
            await self.cancel_scan()
        
        # 清空旧数据
        self.clear_data()
        self._is_scanning = True
        self._error = None
        
        try:
            region_path = Path(region_dir)
            
            # 首先快速统计文件总数
            mca_files = scan_region_dir(region_path)
            self._total_count = len(mca_files)
            
            if self._total_count == 0:
                self._is_scanning = False
                self._scan_progress = 1.0
                return
            
            for mca_file in mca_files:
                try:
                    coord = parse_region_coords(mca_file)
                    if coord is not None:
                        size = mca_file.stat().st_size
                        self._mca_data[coord] = size
                        self._region_meta[coord] = self._scan_region_meta(mca_file)

                    self._scanned_count += 1

                    if self._scanned_count % batch_size == 0:
                        self._scan_progress = self._scanned_count / self._total_count
                        await asyncio.sleep(0)
                except Exception as e:
                    continue
            
            # 最终更新
            self._scan_progress = 1.0
            self._is_scanning = False
            
        except Exception as e:
            self._error = str(e)
            self._is_scanning = False
            raise
    
    def _scan_region_meta(self, region_file: Path) -> Dict[str, Any]:
        biomes: Counter[str] = Counter()
        structures: Counter[str] = Counter()
        structure_positions: list[Dict[str, Any]] = []
        chunk_count = 0
        try:
            import anvil
            region = anvil.Region.from_file(str(region_file))
            sample_points = [(0, 0), (0, 16), (16, 0), (16, 16), (8, 8), (8, 24), (24, 8), (24, 24)]
            for cx, cz in sample_points:
                try:
                    chunk = region.get_chunk(cx, cz)
                    if chunk is None or not hasattr(chunk, "data"):
                        continue
                    chunk_count += 1
                    data = chunk.data
                    self._collect_biomes(data, biomes)
                    self._collect_structures(data, structures, structure_positions)
                except Exception:
                    continue
            if not biomes and not structures:
                for cx in range(0, 32, 4):
                    for cz in range(0, 32, 4):
                        if chunk_count >= 16:
                            break
                        try:
                            chunk = region.get_chunk(cx, cz)
                            if chunk is None or not hasattr(chunk, "data"):
                                continue
                            chunk_count += 1
                            data = chunk.data
                            self._collect_biomes(data, biomes)
                            self._collect_structures(data, structures, structure_positions)
                        except Exception:
                            continue
                    if chunk_count >= 16:
                        break
        except Exception:
            pass

        dominant_biome = biomes.most_common(1)[0][0] if biomes else "unknown"
        dominant_structure = structures.most_common(1)[0][0] if structures else "none"
        return {
            "chunk_count": chunk_count,
            "dominant_biome": dominant_biome,
            "biomes": dict(biomes.most_common(8)),
            "structure_count": sum(structures.values()),
            "dominant_structure": dominant_structure,
            "structures": dict(structures.most_common(8)),
            "structure_positions": structure_positions[:12],
        }

    def _collect_biomes(self, data: Any, counter: Counter[str]) -> None:
        root = self._chunk_root(data)
        sections = self._first(root, "sections", "Sections")
        if self._is_sequence(sections):
            for section in self._iter_values(sections):
                biomes = self._first(section, "biomes", "Biomes")
                palette = self._first(biomes, "palette", "Palette") if self._is_mapping(biomes) else None
                if self._is_sequence(palette):
                    for biome in list(self._iter_values(palette))[:16]:
                        name = self._tag_text(biome)
                        if name:
                            counter[name] += 1
        legacy_biomes = self._first(root, "Biomes", "biomes")
        if self._is_sequence(legacy_biomes):
            for biome in list(self._iter_values(legacy_biomes))[:64]:
                name = self._tag_text(biome)
                if name:
                    counter[name] += 1

    def _collect_structures(self, data: Any, counter: Counter[str], positions: list[Dict[str, Any]]) -> None:
        root = self._chunk_root(data)
        structures = self._first(root, "structures", "Structures")
        starts = self._first(structures, "starts", "Starts") if self._is_mapping(structures) else None
        if self._is_mapping(starts):
            for name, value in self._items(starts):
                if str(name).lower() not in {"references", "starts"} and value is not None:
                    counter[str(name)] += 1
                    pos = self._extract_structure_position(str(name), value)
                    if pos:
                        positions.append(pos)
        refs = self._first(structures, "References", "references") if self._is_mapping(structures) else None
        if self._is_mapping(refs):
            for name, value in self._items(refs):
                try:
                    if len(value) > 0:
                        counter[str(name)] += 1
                except Exception:
                    counter[str(name)] += 1

    def _extract_structure_position(self, name: str, value: Any) -> Optional[Dict[str, Any]]:
        if not self._is_mapping(value):
            return None
        bb = self._first(value, "BB", "bb", "bounding_box")
        pos = self._position_from_bb(name, bb)
        if pos:
            return pos
        children = self._first(value, "Children", "children")
        if self._is_sequence(children):
            for child in self._iter_values(children):
                if not self._is_mapping(child):
                    continue
                pos = self._position_from_bb(name, self._first(child, "BB", "bb", "bounding_box"))
                if pos:
                    return pos
        chunk_x = self._first(value, "ChunkX", "chunkX", "chunk_x")
        chunk_z = self._first(value, "ChunkZ", "chunkZ", "chunk_z")
        if chunk_x is not None and chunk_z is not None:
            try:
                bx = int(self._tag_value(chunk_x)) * 16
                bz = int(self._tag_value(chunk_z)) * 16
                return {"name": name, "block_x": bx, "block_z": bz, "source": "chunk"}
            except Exception:
                return None
        return None

    def _position_from_bb(self, name: str, bb: Any) -> Optional[Dict[str, Any]]:
        raw = self._tag_value(bb)
        if self._is_sequence(raw):
            raw = list(self._iter_values(raw))
        if not isinstance(raw, list) or len(raw) < 6:
            return None
        try:
            return {
                "name": name,
                "block_x": int(self._tag_value(raw[0])),
                "block_y": int(self._tag_value(raw[1])),
                "block_z": int(self._tag_value(raw[2])),
                "source": "bb",
            }
        except Exception:
            return None

    def _chunk_root(self, data: Any) -> Any:
        level = self._first(data, "Level")
        if self._is_mapping(level):
            return level
        return data

    def _first(self, data: Any, *keys: str) -> Any:
        if not self._is_mapping(data):
            return None
        for key in keys:
            value = self._get(data, key)
            if value is not None:
                return value
        return None

    def _is_mapping(self, value: Any) -> bool:
        raw = self._tag_value(value)
        return isinstance(raw, dict) or hasattr(raw, "get") or hasattr(raw, "items")

    def _is_sequence(self, value: Any) -> bool:
        raw = self._tag_value(value)
        if isinstance(raw, (str, bytes, dict)):
            return False
        return isinstance(raw, (list, tuple)) or hasattr(raw, "__iter__")

    def _get(self, data: Any, key: str) -> Any:
        raw = self._tag_value(data)
        try:
            if hasattr(raw, "get"):
                return raw.get(key)
            return raw[key]
        except Exception:
            return None

    def _items(self, data: Any) -> list[tuple[Any, Any]]:
        raw = self._tag_value(data)
        try:
            if hasattr(raw, "items"):
                return list(raw.items())
        except Exception:
            pass
        return []

    def _iter_values(self, data: Any) -> list[Any]:
        raw = self._tag_value(data)
        try:
            return list(raw)
        except Exception:
            return []

    def _tag_text(self, value: Any) -> str:
        raw = getattr(value, "value", value)
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="ignore")
        if isinstance(raw, str):
            return raw
        if hasattr(value, "value") and raw is not None:
            return str(raw)
        return str(raw) if raw is not None else ""

    def _tag_value(self, value: Any) -> Any:
        return getattr(value, "value", value)
    
    async def cancel_scan(self) -> None:
        """取消当前扫描任务"""
        if self._scan_task and not self._scan_task.done():
            self._scan_task.cancel()
            try:
                # 使用 shield 防止取消自己导致死锁
                await asyncio.shield(self._scan_task)
            except (asyncio.CancelledError, RuntimeError):
                pass
        
        self._is_scanning = False
        self._scan_task = None
    
    async def start_scan_async(self, region_dir: str) -> None:
        """
        启动异步扫描（创建后台任务）
        
        Args:
            region_dir: region 目录路径
        """
        # 如果有旧的扫描任务，先取消
        if self._scan_task and not self._scan_task.done():
            await self.cancel_scan()
        
        # 创建新的后台任务
        self._scan_task = asyncio.create_task(
            self.start_silent_scan(region_dir)
        )
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        获取扫描统计信息（单次遍历，避免多次迭代）
        
        Returns:
            包含统计数据的字典
        """
        if not self._mca_data:
            return {
                "total_regions": 0,
                "total_size": 0,
                "avg_size": 0,
                "min_size": 0,
                "max_size": 0,
                "min_coord": None,
                "max_coord": None
            }
        
        total_size = 0
        min_size = float('inf')
        max_size = 0
        min_coord = None
        max_coord = None
        
        for coord, size in self._mca_data.items():
            total_size += size
            if size < min_size:
                min_size = size
            if size > max_size:
                max_size = size
            if min_coord is None or coord < min_coord:
                min_coord = coord
            if max_coord is None or coord > max_coord:
                max_coord = coord
        
        count = len(self._mca_data)
        return {
            "total_regions": count,
            "total_size": total_size,
            "avg_size": total_size // count if count else 0,
            "min_size": min_size,
            "max_size": max_size,
            "min_coord": min_coord,
            "max_coord": max_coord,
        }


import threading

# 全局单例实例
_heatmap_service_instance: Optional[HeatmapService] = None
_heatmap_service_lock = threading.Lock()


def get_heatmap_service() -> HeatmapService:
    """获取区域地图服务单例（线程安全）"""
    global _heatmap_service_instance
    with _heatmap_service_lock:
        if _heatmap_service_instance is None:
            _heatmap_service_instance = HeatmapService()
    return _heatmap_service_instance
