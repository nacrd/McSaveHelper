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
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple, cast

try:
    from PIL import Image as _Image
    Image = _Image
    PIL_AVAILABLE = True
except ImportError:  # pragma: no cover - optional packaged dependency
    Image = cast(Any, None)
    PIL_AVAILABLE = False

from core.mca.map_export_bounds import (
    LoadedMapContent,
    MapContentScanCancelled,
    analyze_loaded_map_content,
)
from core.mca.map_models import BLOCKS_PER_REGION
from core.mca.map_export_png import StreamingPngWriter
from core.mca.topview_renderer import LEAF_TILE_SIZE, render_region_topview
from core.region_utils import parse_region_coords


@dataclass(frozen=True)
class MapImageSpec:
    """导出地图图像的尺寸与区域范围规格。"""
    width: int
    height: int
    estimated_mb: float


@dataclass(frozen=True)
class _StreamingLayout:
    """Immutable geometry and file lookup for a streaming export."""

    block_bounds: Tuple[int, int, int, int]
    scale: int
    spec: MapImageSpec
    min_region_x: int
    max_region_x: int
    min_region_z: int
    max_region_z: int
    strip_origin_x: int
    strip_width: int
    region_paths: Mapping[Tuple[int, int], Path]
    cancel_event: Optional[threading.Event]


@dataclass
class _StreamingProgress:
    """Mutable counters owned by one streaming export."""

    processed_regions: int = 0
    rendered_regions: int = 0


class MapRenderCancelled(Exception):
    """地图渲染被调用方取消。"""


def _ceil_div(numerator: int, denominator: int) -> int:
    """Return the integer ceiling of a division with a positive denominator."""
    return -(-numerator // denominator)


class MapExportRenderer:
    """Compose map-export PNGs from the shared topview renderer."""

    # Match the explorer map canvas backdrop so exports look consistent.
    BACKGROUND = (11, 18, 11)
    MAX_IMAGE_DIMENSION = 32768
    MAX_IMAGE_BYTES = 2048 * 1024 * 1024
    RGB_BYTES_PER_PIXEL = 3
    MAX_PNG_DIMENSION = (1 << 31) - 1

    def __init__(self) -> None:
        """初始化地图导出渲染器。"""
        self.last_rendered_chunks = 0

    def save_map_image(
        self,
        output_path: Path,
        region_files: List[Path],
        bounds: Dict[str, int],
        map_type: str,
        scale: int,
        log: Callable[[str, str], None],
        progress: Callable[[float, str], None],
        *,
        block_bounds: Optional[Tuple[int, int, int, int]] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> MapImageSpec:
        """Render a map to PNG, streaming oversized exports to disk.

        Args:
            output_path: Destination PNG path.
            region_files: MCA region files to include.
            bounds: Inclusive region coordinate range.
            map_type: Requested map style.
            scale: Positive integer blocks per output pixel.
            log: Log callback.
            progress: Progress callback.
            block_bounds: Optional inclusive block crop.
            cancel_event: Optional cancellation event.

        Returns:
            Dimensions and raw RGB memory estimate for the exported image.
        """
        effective_region_files = region_files
        effective_block_bounds = block_bounds
        if block_bounds is None:
            try:
                content = analyze_loaded_map_content(
                    region_files,
                    self._make_cancel_check(cancel_event),
                )
            except MapContentScanCancelled as exc:
                raise MapRenderCancelled(str(exc)) from exc
            effective_region_files = list(content.region_files)
            effective_block_bounds = content.block_bounds
            self._log_loaded_content_crop(content, bounds, log)
        spec = self.calculate_image_spec(
            bounds,
            scale,
            block_bounds=effective_block_bounds,
        )
        if self._fits_in_memory(spec):
            image = self.create_map_image(
                effective_region_files,
                bounds,
                map_type,
                scale,
                log,
                progress,
                block_bounds=effective_block_bounds,
                cancel_event=cancel_event,
            )
            try:
                image.save(output_path, "PNG")
            finally:
                image.close()
            return spec
        del map_type
        log(
            f"图像为 {spec.width}x{spec.height}，启用低内存流式 PNG 导出",
            "INFO",
        )
        self._save_streaming_png(
            output_path=output_path,
            region_files=effective_region_files,
            block_bounds=self._normalize_block_bounds(
                effective_block_bounds,
                bounds,
            ),
            scale=scale,
            spec=spec,
            log=log,
            progress=progress,
            cancel_event=cancel_event,
        )
        return spec

    @staticmethod
    def _log_loaded_content_crop(
        content: LoadedMapContent,
        region_bounds: Dict[str, int],
        log: Callable[[str, str], None],
    ) -> None:
        original_width = (
            region_bounds["max_x"] - region_bounds["min_x"] + 1
        ) * BLOCKS_PER_REGION
        original_height = (
            region_bounds["max_z"] - region_bounds["min_z"] + 1
        ) * BLOCKS_PER_REGION
        min_x, min_z, max_x, max_z = content.block_bounds
        cropped_width = max_x - min_x + 1
        cropped_height = max_z - min_z + 1
        log(
            f"检测到 {content.chunk_count} 个已加载区块；导出边界从 "
            f"{original_width}x{original_height} 裁剪为 "
            f"{cropped_width}x{cropped_height}",
            "INFO",
        )
        if content.skipped_files:
            log(
                f"跳过 {content.skipped_files} 个无法读取的区域文件",
                "WARNING",
            )

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
        if not self._fits_in_memory(spec):
            raise ValueError("图像过大，需通过流式 PNG 导出接口写入文件")
        log(
            f"创建 {spec.width}x{spec.height} 的图像 "
            f"(预计 {spec.estimated_mb:.0f} MB，使用地图俯视渲染)",
            "INFO",
        )

        # Compose directly at the output scale. A full-detail canvas can be
        # dozens of gigabytes even when the requested PNG is reasonably sized.
        canvas = self._stitch_region_tiles(
            region_files=region_files,
            bounds=bounds,
            block_bounds=normalized_block_bounds,
            scale=scale,
            spec=spec,
            log=log,
            progress=progress,
            cancel_event=cancel_event,
        )
        try:
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
        block_bounds: Tuple[int, int, int, int],
        scale: int,
        spec: MapImageSpec,
        log: Callable[[str, str], None],
        progress: Callable[[float, str], None],
        cancel_event: Optional[threading.Event],
    ) -> Any:
        """Paste topview tiles directly into a scaled export canvas."""
        min_rx = bounds["min_x"]
        max_rx = bounds["max_x"]
        min_rz = bounds["min_z"]
        max_rz = bounds["max_z"]
        tile_size = LEAF_TILE_SIZE
        source_min_x, source_min_z, _, _ = block_bounds
        canvas = Image.new(
            "RGB",
            (spec.width, spec.height),
            color=self.BACKGROUND,
        )
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
                    original_tile = tile
                    tile = original_tile.resize(
                        (tile_size, tile_size),
                        Image.Resampling.NEAREST,
                    )
                    original_tile.close()
                self._paste_scaled_tile(
                    canvas=canvas,
                    tile=tile,
                    region_x=region_x,
                    region_z=region_z,
                    source_min_x=source_min_x,
                    source_min_z=source_min_z,
                    scale=scale,
                    spec=spec,
                )
                rendered_regions += 1
                # Approximate chunk count for progress reports (32x32 per region).
                self.last_rendered_chunks += 32 * 32
            finally:
                tile.close()

        if rendered_regions == 0:
            self.last_rendered_chunks = 0
        return canvas

    @staticmethod
    def _paste_scaled_tile(
        canvas: Any,
        tile: Any,
        region_x: int,
        region_z: int,
        source_min_x: int,
        source_min_z: int,
        scale: int,
        spec: MapImageSpec,
    ) -> None:
        """Sample one region tile into the output pixels that start within it."""
        region_min_x = region_x * BLOCKS_PER_REGION
        region_min_z = region_z * BLOCKS_PER_REGION
        start_x = max(0, _ceil_div(region_min_x - source_min_x, scale))
        start_z = max(0, _ceil_div(region_min_z - source_min_z, scale))
        end_x = min(
            spec.width,
            _ceil_div(region_min_x + BLOCKS_PER_REGION - source_min_x, scale),
        )
        end_z = min(
            spec.height,
            _ceil_div(region_min_z + BLOCKS_PER_REGION - source_min_z, scale),
        )
        if end_x <= start_x or end_z <= start_z:
            return
        source_x = source_min_x + start_x * scale - region_min_x
        source_z = source_min_z + start_z * scale - region_min_z
        sampled = tile.transform(
            (end_x - start_x, end_z - start_z),
            Image.Transform.AFFINE,
            (scale, 0, source_x, 0, scale, source_z),
            resample=Image.Resampling.NEAREST,
        )
        try:
            canvas.paste(sampled, (start_x, start_z))
        finally:
            sampled.close()

    def _save_streaming_png(
        self,
        *,
        output_path: Path,
        region_files: List[Path],
        block_bounds: Tuple[int, int, int, int],
        scale: int,
        spec: MapImageSpec,
        log: Callable[[str, str], None],
        progress: Callable[[float, str], None],
        cancel_event: Optional[threading.Event],
    ) -> None:
        """Render region-row strips and stream their scanlines into one PNG."""
        layout = self._build_streaming_layout(
            region_files,
            block_bounds,
            scale,
            spec,
            cancel_event,
        )
        state = _StreamingProgress()
        self.last_rendered_chunks = 0
        cancel_check = self._make_cancel_check(cancel_event)

        with output_path.open("wb") as output:
            writer = StreamingPngWriter(output, spec.width, spec.height)
            for region_z in range(layout.min_region_z, layout.max_region_z + 1):
                self._raise_if_cancelled(cancel_event)
                strip = self._render_streaming_strip(
                    layout,
                    region_z,
                    state,
                    cancel_check,
                    log,
                    progress,
                )
                try:
                    self._write_strip_rows(
                        writer=writer,
                        strip=strip,
                        region_z=region_z,
                        layout=layout,
                    )
                finally:
                    strip.close()
            if state.rendered_regions == 0:
                self.last_rendered_chunks = 0
                raise ValueError("所有 MCA 文件均不可读或不包含可渲染区块")
            writer.finish()

    @staticmethod
    def _build_streaming_layout(
        region_files: List[Path],
        block_bounds: Tuple[int, int, int, int],
        scale: int,
        spec: MapImageSpec,
        cancel_event: Optional[threading.Event],
    ) -> _StreamingLayout:
        min_x, min_z, max_x, max_z = block_bounds
        min_region_x = min_x // BLOCKS_PER_REGION
        max_region_x = max_x // BLOCKS_PER_REGION
        min_region_z = min_z // BLOCKS_PER_REGION
        max_region_z = max_z // BLOCKS_PER_REGION
        region_paths = {
            coords: region_file
            for region_file in region_files
            if (coords := parse_region_coords(region_file)) is not None
            and min_region_x <= coords[0] <= max_region_x
            and min_region_z <= coords[1] <= max_region_z
        }
        return _StreamingLayout(
            block_bounds=block_bounds,
            scale=scale,
            spec=spec,
            min_region_x=min_region_x,
            max_region_x=max_region_x,
            min_region_z=min_region_z,
            max_region_z=max_region_z,
            strip_origin_x=min_region_x * BLOCKS_PER_REGION,
            strip_width=(max_region_x - min_region_x + 1) * BLOCKS_PER_REGION,
            region_paths=region_paths,
            cancel_event=cancel_event,
        )

    def _render_streaming_strip(
        self,
        layout: _StreamingLayout,
        region_z: int,
        state: _StreamingProgress,
        cancel_check: Callable[[], bool],
        log: Callable[[str, str], None],
        progress: Callable[[float, str], None],
    ) -> Any:
        """Render one region row into a caller-owned full-resolution strip."""
        strip = Image.new(
            "RGB",
            (layout.strip_width, BLOCKS_PER_REGION),
            color=self.BACKGROUND,
        )
        try:
            for region_x in range(layout.min_region_x, layout.max_region_x + 1):
                region_file = layout.region_paths.get((region_x, region_z))
                if region_file is None:
                    continue
                state.processed_regions += 1
                total_regions = len(layout.region_paths)
                progress(
                    0.25
                    + (state.processed_regions / max(total_regions, 1)) * 0.65,
                    f"渲染区域 {state.processed_regions}/{total_regions}",
                )
                png = self._render_region_for_export(region_file, cancel_check, log)
                if png is None:
                    continue
                self._paste_streaming_tile(strip, png, region_x, layout)
                state.rendered_regions += 1
                self.last_rendered_chunks += 32 * 32
            return strip
        except Exception:
            strip.close()
            raise

    @staticmethod
    def _paste_streaming_tile(
        strip: Any,
        png: bytes,
        region_x: int,
        layout: _StreamingLayout,
    ) -> None:
        tile = Image.open(io.BytesIO(png)).convert("RGB")
        try:
            if tile.size != (BLOCKS_PER_REGION, BLOCKS_PER_REGION):
                original_tile = tile
                tile = original_tile.resize(
                    (BLOCKS_PER_REGION, BLOCKS_PER_REGION),
                    Image.Resampling.NEAREST,
                )
                original_tile.close()
            paste_x = region_x * BLOCKS_PER_REGION - layout.strip_origin_x
            strip.paste(tile, (paste_x, 0))
        finally:
            tile.close()

    @staticmethod
    def _render_region_for_export(
        region_file: Path,
        cancel_check: Callable[[], bool],
        log: Callable[[str, str], None],
    ) -> Optional[bytes]:
        try:
            png = render_region_topview(
                region_file,
                tile_size=BLOCKS_PER_REGION,
                use_disk_cache=True,
                cancel_check=cancel_check,
            )
        except MapRenderCancelled:
            raise
        except Exception as exc:
            log(f"处理区块文件 {region_file.name} 失败: {exc}", "WARNING")
            return None
        if cancel_check():
            raise MapRenderCancelled("地图导出已取消")
        if not png:
            log(f"区域 {region_file.name} 无可渲染内容，已跳过", "WARNING")
            return None
        return png

    @staticmethod
    def _write_strip_rows(
        *,
        writer: StreamingPngWriter,
        strip: Any,
        region_z: int,
        layout: _StreamingLayout,
    ) -> None:
        min_x, min_z, _, _ = layout.block_bounds
        region_origin_z = region_z * BLOCKS_PER_REGION
        start_y = max(0, _ceil_div(region_origin_z - min_z, layout.scale))
        end_y = min(
            layout.spec.height,
            _ceil_div(
                region_origin_z + BLOCKS_PER_REGION - min_z,
                layout.scale,
            ),
        )
        source_x = min_x - layout.strip_origin_x
        for output_y in range(start_y, end_y):
            if layout.cancel_event is not None and layout.cancel_event.is_set():
                raise MapRenderCancelled("地图导出已取消")
            source_z = min_z + output_y * layout.scale - region_origin_z
            row = strip.transform(
                (layout.spec.width, 1),
                Image.Transform.AFFINE,
                (layout.scale, 0, source_x, 0, 0, source_z),
                resample=Image.Resampling.NEAREST,
            )
            try:
                writer.write_row(row.tobytes())
            finally:
                row.close()

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
        full_width, full_height = MapExportRenderer._source_dimensions(
            bounds,
            block_bounds,
        )
        width = _ceil_div(full_width, scale)
        height = _ceil_div(full_height, scale)
        if (
            width > MapExportRenderer.MAX_PNG_DIMENSION
            or height > MapExportRenderer.MAX_PNG_DIMENSION
        ):
            raise ValueError(
                f"图像尺寸过大 ({width}x{height})，超出限制 "
                f"({MapExportRenderer.MAX_PNG_DIMENSION}px)"
            )
        estimated_bytes = width * height * MapExportRenderer.RGB_BYTES_PER_PIXEL
        estimated_mb = estimated_bytes / (1024 * 1024)
        return MapImageSpec(width, height, estimated_mb)

    @classmethod
    def _fits_in_memory(cls, spec: MapImageSpec) -> bool:
        estimated_bytes = spec.width * spec.height * cls.RGB_BYTES_PER_PIXEL
        return (
            spec.width <= cls.MAX_IMAGE_DIMENSION
            and spec.height <= cls.MAX_IMAGE_DIMENSION
            and estimated_bytes <= cls.MAX_IMAGE_BYTES
        )

    @staticmethod
    def _source_dimensions(
        bounds: Dict[str, int],
        block_bounds: Optional[Tuple[int, int, int, int]],
    ) -> Tuple[int, int]:
        """Return unscaled inclusive width and height for an export request."""
        if block_bounds is not None:
            min_x, min_z, max_x, max_z = block_bounds
            if max_x < min_x or max_z < min_z:
                raise ValueError("方块范围无效")
            return max_x - min_x + 1, max_z - min_z + 1
        region_width = bounds["max_x"] - bounds["min_x"] + 1
        region_height = bounds["max_z"] - bounds["min_z"] + 1
        if region_width <= 0 or region_height <= 0:
            raise ValueError("区域范围无效")
        return region_width * BLOCKS_PER_REGION, region_height * BLOCKS_PER_REGION

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
