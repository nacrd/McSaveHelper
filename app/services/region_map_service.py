"""兼容入口：区域地图服务实现已迁至 app.services.region_map。"""
from app.services.region_map import RegionMapService, ScanProgress

__all__ = ["RegionMapService", "ScanProgress"]
