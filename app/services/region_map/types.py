"""区域地图服务共享类型。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ScanProgress:
    """扫描进度信息"""
    total_files: int = 0
    scanned_files: int = 0
    progress: float = 0.0  # 0.0 到 1.0
    is_scanning: bool = False
    error: Optional[str] = None


__all__ = ["ScanProgress"]
