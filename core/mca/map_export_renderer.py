"""Map export renderer — stitches the same topview tiles used by the map UI.

Export no longer walks MCA chunks with a separate color table. Each region is
rendered through ``core.mca.topview_renderer.render_region_topview`` (the map
display path) and composited into a PNG.
"""
from __future__ import annotations

import io
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, cast

try:
    from PIL import Image as _Image
    Image = _Image
    PIL_AVAILABLE = True
except ImportError:  # pragma: no cover - optional packaged dependency
    Image = cast(Any, None)
    PIL_AVAILABLE = False

from core.mca.map_models import BLOCKS_PER_REGION
from core.mca.topview_renderer import LEAF_TILE_SIZE, render_region_topview
from core.region_utils import parse_region_coords


@dataclass(frozen=True)
class MapImageSpec:
    width: int
    height: int
    estimated_mb: float


class MapRenderCancelled(Exception):
    """地图渲染被调用方取消。"""


def analyze_region_bounds(region_files: List[Path]) -> Dict[str, int]:
    """Return the inclusive region coordinate bounds for valid MCA paths."""
    coords = [
        parsed
        for region_file in region_files
        if (parsed := parse_region_coords(region_file)) is not None
    ]
    if not coords:
        raise ValueError("未找到有效的区域文件坐标")
    return {
        "min_x": min(coord[0] for coord in coords),
        "max_x": max(coord[0] for coord in coords),
        "min_z": min(coord[1] for coord in coords),
        "max_z": max(coord[1] for coord in coords),
    }


class MapExportRenderer:
    """Compose map-export PNGs from the shared topview renderer."""

    # Match the explorer map canvas backdrop so exports look consistent.
    BACKGROUND = (11, 18, 11)

    def __init__(self) -> None:
        self.last_rendered_chunks = 0

    def create_map_image(
        self,
        region_files: List[Path],
        bounds: Dict[str, int],
        map_type: str,
        scale: int,
        log: Callable[[str, str], None],
        progress: Callable[[float, str], None],
        *,
        block_bounds: Optional[Tuple[int, int, int, int]] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> Any:
        """Create a map image by stitching map-display topview region tiles.

        Args:
            region_files: MCA region files to include.
            bounds: Inclusive region coordinate range.
            map_type: Requested style (``topview`` / ``terrain``). Terrain is
                rendered with the same topview path as the map UI.
            scale: Positive integer blocks-per-pixel scale (1 = full detail).
            log: Log callback.
            progress: Progress callback.
            block_bounds: Optional inclusive block crop.
            cancel_event: Optional cancellation event.

        Returns:
            PIL image object (caller owns and must close).
        """
        self._raise_if_cancelled(cancel_event)
        if not PIL_AVAILABLE:
            raise ImportError("需要安装 Pillow 库才能导出地图")
        del map_type  # Map UI topview is the only supported surface export.

        normalized_block_bounds = self._normalize_block_bounds(
            block_bounds,
            bounds,
        )
        spec = self.calculate_image_spec(
            bounds,
            scale,
            block_bounds=block_bounds,
        )
        log(
            f"创建 {spec.width}x{spec.height} 的图像 "
            f"(预计 {spec.estimated_mb:.0f} MB，使用地图俯视渲染)",
            "INFO",
        )

        # Render each region at one block per pixel, then scale/crop.
        canvas = self._stitch_region_tiles(
            region_files=region_files,
            bounds=bounds,
            log=log,
            progress=progress,
            cancel_event=cancel_event,
        )
        try:
            cropped = self._crop_to_block_bounds(canvas, bounds, normalized_block_bounds)
            if cropped is not canvas:
                canvas.close()
                canvas = cropped
            scaled = self._apply_export_scale(canvas, scale, spec)
            if scaled is not canvas:
                canvas.close()
                canvas = scaled
            if self.last_rendered_chunks == 0:
                raise ValueError("所有 MCA 文件均不可读或不包含可渲染区块")
            self._raise_if_cancelled(cancel_event)
            return canvas
        except Exception:
            try:
                canvas.close()
            except Exception:
                # best-effort: never mask the original render error
                pass
            raise

    def _stitch_region_tiles(
        self,
        *,
        region_files: List[Path],
        bounds: Dict[str, int],
        log: Callable[[str, str], None],
        progress: Callable[[float, str], None],
        cancel_event: Optional[threading.Event],
    ) -> Any:
        """Paste LEAF-resolution topview tiles onto a region-aligned canvas."""
        min_rx = bounds["min_x"]
        max_rx = bounds["max_x"]
        min_rz = bounds["min_z"]
        max_rz = bounds["max_z"]
        columns = max_rx - min_rx + 1
        rows = max_rz - min_rz + 1
        tile_size = LEAF_TILE_SIZE
        width = columns * tile_size
        height = rows * tile_size
        canvas = Image.new("RGB", (width, height), color=self.BACKGROUND)
        cancel_check = self._make_cancel_check(cancel_event)
        rendered_regions = 0
        total = len(region_files)
        self.last_rendered_chunks = 0

        for index, region_file in enumerate(region_files):
            self._raise_if_cancelled(cancel_event)
            progress(
                0.25 + (index / max(total, 1)) * 0.70,
                f"渲染区域 {index + 1}/{total}",
            )
            coords = parse_region_coords(region_file)
            if coords is None:
                continue
            region_x, region_z = coords
            if not (min_rx <= region_x <= max_rx and min_rz <= region_z <= max_rz):
                continue
            try:
                png = render_region_topview(
                    region_file,
                    tile_size=tile_size,
                    use_disk_cache=True,
                    cancel_check=cancel_check,
                )
            except MapRenderCancelled:
                raise
            except Exception as exc:
                log(f"处理区块文件 {region_file.name} 失败: {exc}", "WARNING")
                continue
            if cancel_check():
                raise MapRenderCancelled("地图导出已取消")
            if not png:
                log(f"区域 {region_file.name} 无可渲染内容，已跳过", "WARNING")
                continue
            tile = Image.open(io.BytesIO(png)).convert("RGB")
            try:
                if tile.size != (tile_size, tile_size):
                    tile = tile.resize((tile_size, tile_size), Image.Resampling.NEAREST)
                paste_x = (region_x - min_rx) * tile_size
                paste_z = (region_z - min_rz) * tile_size
                canvas.paste(tile, (paste_x, paste_z))
                rendered_regions += 1
                # Approximate chunk count for progress reports (32x32 per region).
                self.last_rendered_chunks += 32 * 32
            finally:
                tile.close()

        if rendered_regions == 0:
            self.last_rendered_chunks = 0
        return canvas

    def _crop_to_block_bounds(
        self,
        canvas: Any,
        region_bounds: Dict[str, int],
        block_bounds: Tuple[int, int, int, int],
    ) -> Any:
        """Crop a 1:1 block canvas to the requested inclusive block rectangle."""
        origin_x = region_bounds["min_x"] * BLOCKS_PER_REGION
        origin_z = region_bounds["min_z"] * BLOCKS_PER_REGION
        min_x, min_z, max_x, max_z = block_bounds
        left = min_x - origin_x
        upper = min_z - origin_z
        right = max_x - origin_x + 1
        lower = max_z - origin_z + 1
        left = max(0, left)
        upper = max(0, upper)
        right = min(canvas.width, right)
        lower = min(canvas.height, lower)
        if left == 0 and upper == 0 and right == canvas.width and lower == canvas.height:
            return canvas
        if right <= left or lower <= upper:
            raise ValueError("方块范围与渲染画布不相交")
        return canvas.crop((left, upper, right, lower))

    def _apply_export_scale(
        self,
        canvas: Any,
        scale: int,
        spec: MapImageSpec,
    ) -> Any:
        """Downsample 1-block-per-pixel canvas to the requested export scale."""
        if scale == 1 and canvas.size == (spec.width, spec.height):
            return canvas
        if canvas.size == (spec.width, spec.height):
            return canvas
        return canvas.resize(
            (spec.width, spec.height),
            Image.Resampling.NEAREST,
        )

    @staticmethod
    def calculate_image_spec(
        bounds: Dict[str, int],
        scale: int,
        *,
        block_bounds: Optional[Tuple[int, int, int, int]] = None,
    ) -> MapImageSpec:
        """计算导出图像尺寸与预估内存。"""
        if not isinstance(scale, int) or isinstance(scale, bool) or scale <= 0:
            raise ValueError("缩放比例必须是正整数")
        if block_bounds is None:
            region_width = bounds["max_x"] - bounds["min_x"] + 1
            region_height = bounds["max_z"] - bounds["min_z"] + 1
            full_width = region_width * BLOCKS_PER_REGION
            full_height = region_height * BLOCKS_PER_REGION
            width = full_width // scale
            height = full_height // scale
        else:
            min_x, min_z, max_x, max_z = block_bounds
            if max_x < min_x or max_z < min_z:
                raise ValueError("方块范围无效")
            full_width = max_x - min_x + 1
            full_height = max_z - min_z + 1
            width = (full_width + scale - 1) // scale
            height = (full_height + scale - 1) // scale
        max_dimension = 32768
        if width > max_dimension or height > max_dimension:
            needed_scale = max(
                full_width // max_dimension + 1,
                full_height // max_dimension + 1,
            )
            raise ValueError(
                f"图像尺寸过大 ({width}x{height})，超出限制 "
                f"({max_dimension}px)。请将缩放比例调整为至少 1:{needed_scale}"
            )
        estimated_mb = width * height * 3 / (1024 * 1024)
        if estimated_mb > 2048:
            raise ValueError(
                f"预计图像内存占用约 {estimated_mb:.0f} MB，"
                "超出安全限制 (2048 MB)。请增大缩放比例以减小图像尺寸"
            )
        return MapImageSpec(width, height, estimated_mb)

    @staticmethod
    def _make_cancel_check(
        cancel_event: Optional[threading.Event],
    ) -> Callable[[], bool]:
        if cancel_event is None:
            return lambda: False
        return cancel_event.is_set

    @staticmethod
    def _raise_if_cancelled(
        cancel_event: Optional[threading.Event],
    ) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise MapRenderCancelled("地图导出已取消")

    @staticmethod
    def _normalize_block_bounds(
        block_bounds: Optional[Tuple[int, int, int, int]],
        region_bounds: Dict[str, int],
    ) -> Tuple[int, int, int, int]:
        if block_bounds is not None:
            if len(block_bounds) != 4:
                raise ValueError("方块范围必须是 (min_x, min_z, max_x, max_z)")
            min_x, min_z, max_x, max_z = (int(value) for value in block_bounds)
            if max_x < min_x or max_z < min_z:
                raise ValueError("方块范围无效")
            return min_x, min_z, max_x, max_z
        min_rx = region_bounds["min_x"]
        max_rx = region_bounds["max_x"]
        min_rz = region_bounds["min_z"]
        max_rz = region_bounds["max_z"]
        return (
            min_rx * BLOCKS_PER_REGION,
            min_rz * BLOCKS_PER_REGION,
            (max_rx + 1) * BLOCKS_PER_REGION - 1,
            (max_rz + 1) * BLOCKS_PER_REGION - 1,
        )
