"""地图导出服务。

服务负责解析维度和选择范围，并将底层渲染结果以原子方式写入 PNG。
"""
from __future__ import annotations

import os
import tempfile
import threading
import traceback
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from core.logger import logger
from core.region_utils import (
    discover_dimension_region_dirs,
    parse_region_coords,
    scan_region_dir,
)
from core.mca.map_export_renderer import (
    MapExportRenderer,
    MapImageSpec,
    MapRenderCancelled,
    PIL_AVAILABLE,
    analyze_region_bounds,
)
from core.mca.map_models import MapExportSpec, MapSelection, SUPPORTED_MAP_STYLES

__all__ = [
    "MapExportService",
    "MapExportSpec",
    "MapImageSpec",
    "MapSelection",
    "PIL_AVAILABLE",
]

LogFn = Callable[[str, str], None]
ProgressFn = Callable[[float, str], None]
BlockBounds = Tuple[int, int, int, int]


@dataclass(frozen=True)
class _RenderJob:
    """渲染并写盘所需的不可变参数包。"""

    region_files: tuple[Path, ...]
    bounds: Mapping[str, int]
    style: str
    scale: int
    output_path: Path
    selection_bounds: Optional[BlockBounds]
    cancel_event: Optional[threading.Event]


class MapExportService:
    """地图导出服务。

    负责解析维度/选择范围，调用渲染器，并以同目录临时文件原子写出 PNG。
    """

    def __init__(self) -> None:
        """初始化渲染器；缺少 Pillow 时立即失败。"""
        self._renderer = MapExportRenderer()
        if not PIL_AVAILABLE:
            raise ImportError(
                "需要安装 Pillow 库才能使用地图导出功能\n"
                "请运行: pip install Pillow"
            )

    def export_map(
        self,
        world_path: Path,
        output_path: Path,
        map_type: str = "topview",
        scale: int = 1,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        log_callback: Optional[Callable[[str, str], None]] = None,
        *,
        spec: Optional[MapExportSpec] = None,
        region_dir: Optional[Path] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> Dict[str, Any]:
        """导出地图，旧式参数和领域规格均可使用。

        Args:
            world_path: 存档路径。
            output_path: 输出 PNG 路径。
            map_type: 旧 API 的地图样式。
            scale: 旧 API 的正整数缩放比例。
            progress_callback: 进度回调。
            log_callback: 日志回调。
            spec: 可选的维度/样式/选择规格。
            region_dir: 显式 region 目录，优先于维度发现。
            cancel_event: 设置后尽快取消导出。
        """
        dimension_id = str(
            getattr(spec, "dimension_id", "overworld")
            if spec is not None
            else "overworld"
        ).strip() or "overworld"
        results: Dict[str, Any] = {
            "success": False,
            "output_path": None,
            "dimensions": (0, 0),
            "chunks_processed": 0,
            "cancelled": False,
            "dimension_id": dimension_id,
            "region_bounds": None,
            "selection_bounds": None,
            "error": None,
        }
        log = partial(self._emit_log, callback=log_callback)
        progress = partial(self._emit_progress, callback=progress_callback)

        try:
            world_path = Path(world_path)
            output_path = Path(output_path)
            dimension_id = self._dimension_id(spec)
            results["dimension_id"] = dimension_id
            style = self._effective_style(map_type, spec)
            effective_scale = self._effective_scale(scale, spec)
            self._check_cancelled(cancel_event)
            if not world_path.exists():
                raise FileNotFoundError(f"存档路径不存在: {world_path}")

            from core.performance import get_tracker

            tracker = get_tracker()
            with tracker.track(
                "地图导出",
                {"world": world_path.name, "type": style, "dimension": dimension_id},
            ):
                log(f"开始导出地图: {world_path}", "INFO")
                region_files, bounds, selection_bounds = self._prepare_regions(
                    world_path,
                    dimension_id,
                    region_dir,
                    spec,
                    cancel_event,
                    log,
                    progress,
                )
                results["selection_bounds"] = selection_bounds
                results["region_bounds"] = bounds
                image_size, chunks_processed = self._render_and_save(
                    _RenderJob(
                        region_files=tuple(region_files),
                        bounds=bounds,
                        style=style,
                        scale=effective_scale,
                        output_path=output_path,
                        selection_bounds=selection_bounds,
                        cancel_event=cancel_event,
                    ),
                    log,
                    progress,
                )

                results["success"] = True
                results["output_path"] = str(output_path)
                results["dimensions"] = image_size
                results["chunks_processed"] = chunks_processed
                tracker.increment_files(chunks_processed)
                progress(1.0, "导出完成")

        except MapRenderCancelled:
            results["cancelled"] = True
            results["error"] = "地图导出已取消"
            log("地图导出已取消", "INFO")
        except Exception as exc:
            if cancel_event is not None and cancel_event.is_set():
                results["cancelled"] = True
            results["error"] = str(exc)
            log(f"导出失败: {exc}", "ERROR")
            logger.error(traceback.format_exc(), module="MapExport")
        if results["cancelled"]:
            results["output_path"] = None

        return results

    @staticmethod
    def _emit_log(
        message: str,
        level: str = "INFO",
        *,
        callback: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        if level == "ERROR":
            logger.error(message, module="MapExport")
        elif level == "WARNING":
            logger.warning(message, module="MapExport")
        else:
            logger.info(message, module="MapExport")
        if callback:
            callback(message, level)

    @staticmethod
    def _emit_progress(
        value: float,
        message: str,
        *,
        callback: Optional[Callable[[float, str], None]] = None,
    ) -> None:
        if callback:
            callback(value, message)

    def _prepare_regions(
        self,
        world_path: Path,
        dimension_id: str,
        region_dir: Optional[Path],
        spec: Optional[MapExportSpec],
        cancel_event: Optional[threading.Event],
        log: LogFn,
        progress: ProgressFn,
    ) -> Tuple[
        list[Path],
        Dict[str, int],
        Optional[BlockBounds],
    ]:
        """解析目录并仅保留与选择范围相交的区域文件。"""
        self._check_cancelled(cancel_event)
        progress(0.05, "扫描区块文件...")
        selected_region_dir = self._resolve_region_dir(
            world_path,
            dimension_id,
            region_dir,
            spec is not None,
        )
        region_files = scan_region_dir(selected_region_dir)
        if not region_files:
            raise ValueError(
                f"维度 {dimension_id} 未找到区块文件: {selected_region_dir}"
            )

        selection_bounds = self._selection_bounds(spec)
        if selection_bounds is not None:
            region_files = self._filter_region_files(
                region_files,
                selection_bounds,
            )
            if not region_files:
                raise ValueError(
                    f"选择范围 {selection_bounds} 与维度 {dimension_id} "
                    "的区块文件不相交"
                )
        self._check_cancelled(cancel_event)
        bounds = analyze_region_bounds(region_files)
        log(f"找到 {len(region_files)} 个区块文件", "INFO")
        progress(0.15, "分析地图范围...")
        return region_files, bounds, selection_bounds

    def _render_and_save(
        self,
        job: _RenderJob,
        log: LogFn,
        progress: ProgressFn,
    ) -> Tuple[Tuple[int, int], int]:
        """渲染并通过同目录临时文件原子替换输出。

        Args:
            job: 渲染参数包。
            log: 日志回调。
            progress: 进度回调。

        Returns:
            tuple: ``((width, height), chunks_processed)``。
        """
        output_path = job.output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{output_path.stem}.",
            suffix=".tmp",
            dir=str(output_path.parent),
        )
        os.close(fd)
        temporary_path: Optional[Path] = Path(temporary_name)
        image: Any = None
        try:
            progress(0.25, "创建地图图像...")
            renderer_kwargs: Dict[str, Any] = {}
            if job.selection_bounds is not None:
                renderer_kwargs["block_bounds"] = job.selection_bounds
            if job.cancel_event is not None:
                renderer_kwargs["cancel_event"] = job.cancel_event
            image = self._renderer.create_map_image(
                list(job.region_files),
                dict(job.bounds),
                job.style,
                job.scale,
                log,
                progress,
                **renderer_kwargs,
            )
            self._check_cancelled(job.cancel_event)
            image_size = (int(image.size[0]), int(image.size[1]))
            progress(0.95, "保存图像...")
            image.save(temporary_path, "PNG")
            image.close()
            image = None
            self._check_cancelled(job.cancel_event)
            assert temporary_path is not None
            temporary_path.replace(output_path)
            temporary_path = None
            log(f"地图已保存: {output_path}", "INFO")
            return image_size, self._renderer.last_rendered_chunks
        finally:
            if image is not None:
                try:
                    image.close()
                except Exception:
                    # best-effort：关闭失败不应掩盖主异常。
                    pass
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    @staticmethod
    def _dimension_id(spec: Optional[MapExportSpec]) -> str:
        value = getattr(spec, "dimension_id", "overworld") if spec is not None else "overworld"
        dimension_id = str(value).strip()
        if not dimension_id:
            raise ValueError("维度 ID 不能为空")
        return dimension_id

    @staticmethod
    def _effective_style(map_type: str, spec: Optional[MapExportSpec]) -> str:
        supplied = str(map_type).strip().lower()
        if supplied not in SUPPORTED_MAP_STYLES:
            raise ValueError(f"不支持的地图样式: {map_type}")
        if spec is None:
            return supplied
        style = str(getattr(spec, "style", supplied)).strip().lower()
        if style not in SUPPORTED_MAP_STYLES:
            raise ValueError(f"不支持的地图样式: {style}")
        return style

    @staticmethod
    def _effective_scale(scale: int, spec: Optional[MapExportSpec]) -> int:
        if not isinstance(scale, int) or isinstance(scale, bool) or scale <= 0:
            raise ValueError("缩放比例必须是正整数")
        value: Any = getattr(spec, "scale", scale) if spec is not None else scale
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError("缩放比例必须是正整数")
        return value

    @staticmethod
    def _resolve_region_dir(
        world_path: Path,
        dimension_id: str,
        explicit_region_dir: Optional[Path],
        use_discovery: bool,
    ) -> Path:
        if explicit_region_dir is not None:
            path = Path(explicit_region_dir)
            if not path.is_dir():
                raise ValueError(f"显式 region 目录不存在或不是目录: {path}")
            return path
        if not use_discovery:
            path = world_path / "region"
            if not path.is_dir():
                raise ValueError("未找到主世界 region 目录")
            return path
        dimensions = discover_dimension_region_dirs(world_path)
        aliases = {dimension_id}
        if dimension_id == "minecraft:overworld":
            aliases.add("overworld")
        match = next((item for item in dimensions if item.id in aliases), None)
        if match is None:
            available = ", ".join(item.id for item in dimensions) or "无"
            raise ValueError(
                f"未找到维度 {dimension_id} 的 region 目录（可用维度: {available}）"
            )
        return match.region_dir

    @staticmethod
    def _selection_bounds(
        spec: Optional[MapExportSpec],
    ) -> Optional[Tuple[int, int, int, int]]:
        if spec is None:
            return None
        selection = getattr(spec, "selection", None)
        if selection is None:
            return None
        value: Any = getattr(selection, "block_bounds", None)
        if callable(value):
            value = value()
        if value is None:
            value = selection
        return MapExportService._coerce_bounds(value)

    @staticmethod
    def _coerce_bounds(value: Any) -> Tuple[int, int, int, int]:
        if isinstance(value, Mapping):
            keys = ("min_x", "min_z", "max_x", "max_z")
            try:
                return tuple(int(value[key]) for key in keys)  # type: ignore[return-value]
            except KeyError as exc:
                raise ValueError("选择范围缺少坐标字段") from exc
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            if len(value) != 4:
                raise ValueError("选择范围必须包含四个坐标")
            return tuple(int(item) for item in value)  # type: ignore[return-value]
        try:
            return (
                int(getattr(value, "min_x")),
                int(getattr(value, "min_z")),
                int(getattr(value, "max_x")),
                int(getattr(value, "max_z")),
            )
        except AttributeError as exc:
            raise ValueError("无法读取选择范围坐标") from exc

    @staticmethod
    def _filter_region_files(
        region_files: Sequence[Path],
        selection_bounds: Tuple[int, int, int, int],
    ) -> list[Path]:
        min_x, min_z, max_x, max_z = selection_bounds
        if max_x < min_x or max_z < min_z:
            raise ValueError("选择范围无效")
        min_region_x, min_region_z = min_x // 512, min_z // 512
        max_region_x, max_region_z = max_x // 512, max_z // 512
        filtered: list[Path] = []
        for region_file in region_files:
            coords = parse_region_coords(region_file)
            if coords is None:
                continue
            region_x, region_z = coords
            if (
                min_region_x <= region_x <= max_region_x
                and min_region_z <= region_z <= max_region_z
            ):
                filtered.append(region_file)
        return filtered

    @staticmethod
    def _check_cancelled(cancel_event: Optional[threading.Event]) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise MapRenderCancelled("地图导出已取消")
