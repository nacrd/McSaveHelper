"""Map Export Service - 地图导出服务

将存档地图导出为 PNG 图片（俯视图/地形图）
"""
from pathlib import Path
from typing import Dict, Any, Optional, Callable
import traceback

from core.logger import logger
from core.region_utils import scan_region_dir
from core.mca.map_export_renderer import (
    MapExportRenderer,
    MapImageSpec,
    PIL_AVAILABLE,
    analyze_region_bounds,
)

__all__ = ["MapExportService", "MapImageSpec", "PIL_AVAILABLE"]


class MapExportService:
    """地图导出服务"""

    def __init__(self) -> None:
        self._renderer = MapExportRenderer()
        if not PIL_AVAILABLE:
            raise ImportError(
                "需要安装 Pillow 库才能使用地图导出功能\n请运行: pip install Pillow")

    def export_map(
        self,
        world_path: Path,
        output_path: Path,
        map_type: str = "topview",  # topview 或 terrain
        scale: int = 1,  # 缩放比例
        progress_callback: Optional[Callable[[float, str], None]] = None,
        log_callback: Optional[Callable[[str, str], None]] = None,
    ) -> Dict[str, Any]:
        """导出地图

        Args:
            world_path: 存档路径
            output_path: 输出文件路径
            map_type: 地图类型 (topview: 俯视图, terrain: 地形图)
            scale: 缩放比例
            progress_callback: 进度回调
            log_callback: 日志回调

        Returns:
            导出结果字典
        """
        results: Dict[str, Any] = {
            "success": False,
            "output_path": None,
            "dimensions": (0, 0),
            "chunks_processed": 0,
        }

        def log(msg: str, level: str = "INFO") -> None:
            logger.info(msg, module="MapExport")
            if log_callback:
                log_callback(msg, level)

        def progress(value: float, msg: str) -> None:
            if progress_callback:
                progress_callback(value, msg)

        try:
            if not world_path.exists():
                raise FileNotFoundError(f"存档路径不存在: {world_path}")

            from core.performance import get_tracker
            tracker = get_tracker()
            with tracker.track("地图导出", {"world": world_path.name, "type": map_type}):
                log(f"开始导出地图: {world_path}", "INFO")
                progress(0.05, "扫描区块文件...")

            # 只扫描主世界的区块文件（避免不同维度区块重叠）
            region_dir = world_path / "region"
            if not region_dir.exists():
                raise ValueError("未找到主世界 region 目录")

            region_files = scan_region_dir(region_dir)

            if not region_files:
                raise ValueError("未找到区块文件")

            log(f"找到 {len(region_files)} 个区块文件", "INFO")

            # 分析区块范围
            progress(0.15, "分析地图范围...")
            bounds = analyze_region_bounds(region_files)
            log(
                f"地图范围: X[{
                    bounds['min_x']} ~ {
                    bounds['max_x']}], Z[{
                    bounds['min_z']} ~ {
                    bounds['max_z']}]",
                "INFO")

            # 创建地图图像
            progress(0.25, "创建地图图像...")
            image = self._renderer.create_map_image(
                region_files,
                bounds,
                map_type,
                scale,
                log,
                progress,
            )

            # 保存图像
            progress(0.95, "保存图像...")
            # 在关闭前获取图像尺寸，避免访问已关闭的图像对象
            image_size = image.size
            try:
                image.save(output_path, "PNG")
                log(f"地图已保存: {output_path}", "INFO")
            finally:
                # 确保关闭图像对象，释放文件句柄
                image.close()

            results["success"] = True
            results["output_path"] = str(output_path)
            results["dimensions"] = image_size
            results["chunks_processed"] = self._renderer.last_rendered_chunks
            tracker.increment_files(self._renderer.last_rendered_chunks)

            progress(1.0, "导出完成")

        except Exception as e:
            error_msg = f"导出失败: {e}"
            log(error_msg, "ERROR")
            logger.error(traceback.format_exc(), module="MapExport")

        return results
