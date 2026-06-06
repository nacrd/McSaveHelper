"""
存档热力图后台扫描服务 (HeatmapService)

提供异步、非阻塞的区域文件扫描能力，
支持进度追踪和数据查询。
"""
import asyncio
import re
import os
from pathlib import Path
from typing import Any, Dict, Tuple, Optional
from dataclasses import dataclass


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
    存档热力图后台扫描服务（单例模式）
    
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
    
    def get_data_snapshot(self) -> Dict[Tuple[int, int], int]:
        """
        获取数据快照（get_all_data 的别名，保持兼容性）
        """
        return self.get_all_data()
    
    def clear_data(self) -> None:
        """清空所有缓存数据"""
        self._mca_data.clear()
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
            mca_files = list(region_path.glob("r.*.*.mca"))
            self._total_count = len(mca_files)
            
            if self._total_count == 0:
                self._is_scanning = False
                self._scan_progress = 1.0
                return
            
            # 分批处理
            batch: list = []
            
            for mca_file in mca_files:
                try:
                    # 解析坐标
                    coord = self._parse_mca_filename(mca_file.stem)
                    if coord is not None:
                        # 获取文件大小
                        size = mca_file.stat().st_size
                        self._mca_data[coord] = size
                    
                    self._scanned_count += 1
                    
                    # 达到批次大小时更新进度
                    if len(batch) >= batch_size:
                        self._scan_progress = self._scanned_count / self._total_count
                        batch.clear()
                        # 让出控制权，允许UI更新
                        await asyncio.sleep(0)
                        
                except Exception as e:
                    # 单个文件错误不影响整体
                    continue
            
            # 最终更新
            self._scan_progress = 1.0
            self._is_scanning = False
            
        except Exception as e:
            self._error = str(e)
            self._is_scanning = False
            raise
    
    def _parse_mca_filename(self, filename: str) -> Optional[Tuple[int, int]]:
        """
        解析 MCA 文件名获取坐标
        
        Args:
            filename: 文件名（不含扩展名），如 "r.0.0"
            
        Returns:
            (x, z) 坐标元组，或 None 如果解析失败
        """
        # 匹配 r.x.z 格式
        pattern = r'^r\.(-?\d+)\.(-?\d+)$'
        match = re.match(pattern, filename)
        
        if match:
            x = int(match.group(1))
            z = int(match.group(2))
            return (x, z)
        
        return None
    
    async def cancel_scan(self) -> None:
        """取消当前扫描任务"""
        if self._scan_task and not self._scan_task.done():
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
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
        获取扫描统计信息
        
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
        
        sizes = list(self._mca_data.values())
        coords = list(self._mca_data.keys())
        
        return {
            "total_regions": len(self._mca_data),
            "total_size": sum(sizes),
            "avg_size": sum(sizes) // len(sizes) if sizes else 0,
            "min_size": min(sizes) if sizes else 0,
            "max_size": max(sizes) if sizes else 0,
            "min_coord": min(coords, key=lambda c: (c[0], c[1])) if coords else None,
            "max_coord": max(coords, key=lambda c: (c[0], c[1])) if coords else None,
        }


# 全局单例实例
_heatmap_service_instance: Optional[HeatmapService] = None


def get_heatmap_service() -> HeatmapService:
    """获取热力图服务单例"""
    global _heatmap_service_instance
    if _heatmap_service_instance is None:
        _heatmap_service_instance = HeatmapService()
    return _heatmap_service_instance
