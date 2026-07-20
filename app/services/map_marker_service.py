"""地图标记的应用级持久化服务。"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable, List

from core.io_atomic import atomic_write_text
from core.mca.map_models import MapMarker


class MapMarkerServiceError(ValueError):
    """标记数据或存储位置不符合服务约束。"""


class MapMarkerService:
    """在应用数据目录中按世界隔离并原子保存地图标记。"""

    SCHEMA_VERSION = 1
    WORLD_KEY_LENGTH = 16

    def __init__(self, root: Path | str | None = None) -> None:
        default_root = Path.home() / ".mcsavehelper" / "map_markers"
        self._root = Path(root or default_root).expanduser().resolve()
        self._lock = threading.RLock()

    @property
    def root(self) -> Path:
        """返回标记仓库根目录。"""
        return self._root

    def world_key(self, world: Path | str) -> str:
        """根据解析后的世界路径生成稳定的短哈希键。"""
        resolved = self._resolve_world(world)
        digest = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()
        return digest[:self.WORLD_KEY_LENGTH]

    def storage_path(self, world: Path | str) -> Path:
        """返回世界对应的应用数据文件路径，不创建任何目录。"""
        resolved = self._resolve_world(world)
        self._assert_external_storage(resolved)
        digest = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()
        return self._root / f"{digest[:self.WORLD_KEY_LENGTH]}.json"

    def list(
        self,
        world: Path | str,
        dimension_id: str | None = None,
        include_disabled: bool = False,
    ) -> List[MapMarker]:
        """列出世界标记，并返回与持久化状态隔离的副本。"""
        self._validate_dimension_filter(dimension_id)
        with self._lock:
            markers = self._load(world)
            filtered = [
                marker
                for marker in markers
                if (dimension_id is None or marker.dimension_id == dimension_id)
                and (include_disabled or marker.enabled)
            ]
            return [self._copy_marker(marker) for marker in filtered]

    def upsert(self, world: Path | str, marker: MapMarker) -> MapMarker:
        """按标记 ID 新增或替换记录，并返回保存后的副本。"""
        replacement = self._validated_copy(marker)
        with self._lock:
            by_id = {item.id: item for item in self._load(world)}
            by_id[replacement.id] = replacement
            self._write(world, self._sort_markers(by_id.values()))
        return self._copy_marker(replacement)

    def delete(self, world: Path | str, marker_id: str) -> bool:
        """删除指定 ID 的标记，并报告记录是否存在。"""
        clean_id = self._validate_marker_id(marker_id)
        with self._lock:
            markers = self._load(world)
            remaining = [marker for marker in markers if marker.id != clean_id]
            if len(remaining) == len(markers):
                return False
            self._write(world, remaining)
            return True

    def clear(
        self,
        world: Path | str,
        dimension_id: str | None = None,
    ) -> int:
        """清空全部或指定维度的标记，并返回删除数量。"""
        self._validate_dimension_filter(dimension_id)
        with self._lock:
            markers = self._load(world)
            if dimension_id is None:
                remaining: List[MapMarker] = []
            else:
                remaining = [
                    marker
                    for marker in markers
                    if marker.dimension_id != dimension_id
                ]
            removed = len(markers) - len(remaining)
            if removed:
                self._write(world, remaining)
            return removed

    def _load(self, world: Path | str) -> List[MapMarker]:
        path = self.storage_path(world)
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            marker_data = self._validate_payload(payload)
            by_id: dict[str, MapMarker] = {}
            for raw_marker in marker_data:
                marker = MapMarker.from_dict(deepcopy(raw_marker))
                validated = self._validated_copy(marker)
                by_id[validated.id] = validated
            return self._sort_markers(by_id.values())
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError, KeyError):
            self._quarantine(path)
            return []

    def _write(self, world: Path | str, markers: Iterable[MapMarker]) -> None:
        path = self.storage_path(world)
        self._root.mkdir(parents=True, exist_ok=True)
        ordered = self._sort_markers(markers)
        payload = {
            "version": self.SCHEMA_VERSION,
            "markers": [deepcopy(marker.to_dict()) for marker in ordered],
        }
        try:
            content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        except (TypeError, ValueError) as exc:
            raise MapMarkerServiceError(f"地图标记无法序列化: {exc}") from exc

        atomic_write_text(path, content, newline="\n")

    @classmethod
    def _validate_payload(cls, payload: Any) -> List[dict[str, Any]]:
        if not isinstance(payload, dict):
            raise MapMarkerServiceError("地图标记文件根节点必须是对象")
        if payload.get("version") != cls.SCHEMA_VERSION:
            raise MapMarkerServiceError("地图标记文件版本不受支持")
        markers = payload.get("markers")
        if not isinstance(markers, list):
            raise MapMarkerServiceError("地图标记列表格式无效")
        if not all(isinstance(marker, dict) for marker in markers):
            raise MapMarkerServiceError("地图标记记录必须是对象")
        return markers

    @classmethod
    def _validated_copy(cls, marker: MapMarker) -> MapMarker:
        if not isinstance(marker, MapMarker):
            raise MapMarkerServiceError("只能保存 MapMarker 类型的地图标记")
        clone = cls._copy_marker(marker)
        cls._validate_marker_id(clone.id)
        if not isinstance(clone.name, str) or not clone.name.strip():
            raise MapMarkerServiceError("地图标记名称不能为空")
        if not isinstance(clone.dimension_id, str) or not clone.dimension_id.strip():
            raise MapMarkerServiceError("地图标记维度不能为空")
        for field_name in ("x", "y", "z"):
            value = getattr(clone, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise MapMarkerServiceError(f"地图标记坐标 {field_name} 必须是整数")
        if not isinstance(clone.enabled, bool) or not isinstance(clone.show_label, bool):
            raise MapMarkerServiceError("地图标记显示状态必须是布尔值")
        if not isinstance(clone.metadata, dict):
            raise MapMarkerServiceError("地图标记 metadata 必须是对象")
        try:
            json.dumps(clone.to_dict(), ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise MapMarkerServiceError(f"地图标记包含无法序列化的数据: {exc}") from exc
        return clone

    @staticmethod
    def _copy_marker(marker: MapMarker) -> MapMarker:
        return MapMarker.from_dict(deepcopy(marker.to_dict()))

    @staticmethod
    def _sort_markers(markers: Iterable[MapMarker]) -> List[MapMarker]:
        return sorted(
            markers,
            key=lambda marker: (
                marker.group.casefold(),
                marker.name.casefold(),
                marker.id.casefold(),
            ),
        )

    @staticmethod
    def _validate_marker_id(marker_id: str) -> str:
        if not isinstance(marker_id, str) or not marker_id.strip():
            raise MapMarkerServiceError("地图标记 ID 不能为空")
        return marker_id

    @staticmethod
    def _validate_dimension_filter(dimension_id: str | None) -> None:
        if dimension_id is not None and (
            not isinstance(dimension_id, str) or not dimension_id.strip()
        ):
            raise MapMarkerServiceError("维度标识不能为空")

    @staticmethod
    def _resolve_world(world: Path | str) -> Path:
        if isinstance(world, str) and not world.strip():
            raise MapMarkerServiceError("存档路径不能为空")
        try:
            return Path(world).expanduser().resolve()
        except (TypeError, ValueError, OSError) as exc:
            raise MapMarkerServiceError(f"存档路径无效: {exc}") from exc

    def _assert_external_storage(self, world: Path) -> None:
        try:
            self._root.relative_to(world)
        except ValueError:
            return
        raise MapMarkerServiceError("地图标记存储目录不能位于 Minecraft 存档内")

    @staticmethod
    def _quarantine(path: Path) -> None:
        broken_path = path.with_suffix(".broken")
        try:
            os.replace(path, broken_path)
        except OSError:
            return
