"""NbtLoader - NBT 数据延迟加载器。

按需加载并缓存 level.dat、玩家数据与区块 NBT。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

import core.nbt as nbtlib
from core.nbt import Compound, File

from .mod_metadata import detect_mod_metadata
from .models import WorldInfo

LogFn = Callable[[str, str], None]


def _tag_get(container: Any, key: str, default: Any = None) -> Any:
    """安全读取类映射 NBT 容器字段。"""
    if container is None or not hasattr(container, "get"):
        return default
    try:
        value = container.get(key, default)
    except (TypeError, KeyError, AttributeError):
        return default
    return default if value is None else value


def _string_list(value: Any) -> Optional[list[str]]:
    """将 NBT 列表投影为 Python 字符串列表。"""
    if not value:
        return None
    try:
        return [str(item) for item in value]
    except TypeError:
        return None


def _extract_data_packs(data: Any) -> Optional[Dict[str, list[str]]]:
    """从 Data.DataPacks 提取启用/禁用列表。"""
    packs = _tag_get(data, "DataPacks")
    if packs is None:
        return None
    enabled = _string_list(_tag_get(packs, "Enabled", [])) or []
    disabled = _string_list(_tag_get(packs, "Disabled", [])) or []
    if not enabled and not disabled:
        return None
    return {"enabled": enabled, "disabled": disabled}


def _extract_world_gen(data: Any) -> tuple[Any, Any, Any]:
    """返回 ``(seed, generate_features, bonus_chest)``。"""
    settings = _tag_get(data, "WorldGenSettings")
    if settings is None:
        return None, None, None
    return (
        _tag_get(settings, "seed"),
        _tag_get(settings, "generate_features"),
        _tag_get(settings, "bonus_chest"),
    )


def build_world_info_from_level_root(root: Any) -> WorldInfo:
    """从已加载的 level.dat 根节点构造 :class:`WorldInfo`。

    Args:
        root: ``load`` 返回的文件/根标签。

    Returns:
        WorldInfo: 世界展示用快照。
    """
    data = _tag_get(root, "Data") or {}
    version_tag = _tag_get(data, "Version") or {}
    seed, generate_features, bonus_chest = _extract_world_gen(data)
    data_packs = _extract_data_packs(data)
    server_brands = _string_list(_tag_get(data, "ServerBrands"))
    mod_metadata = detect_mod_metadata(
        root,
        data,
        data_packs=data_packs,
        server_brands=server_brands,
    )
    return WorldInfo(
        version=_tag_get(version_tag, "Id", 0) or 0,
        version_name=_tag_get(version_tag, "Name"),
        game_type=_tag_get(data, "GameType"),
        last_played=_tag_get(data, "LastPlayed"),
        spawn_x=_tag_get(data, "SpawnX"),
        spawn_y=_tag_get(data, "SpawnY"),
        spawn_z=_tag_get(data, "SpawnZ"),
        level_name=_tag_get(data, "LevelName"),
        difficulty=_tag_get(data, "Difficulty"),
        hardcore=_tag_get(data, "hardcore"),
        allow_commands=_tag_get(data, "allowCommands"),
        seed=seed,
        day_time=_tag_get(data, "DayTime"),
        time=_tag_get(data, "Time"),
        rain_time=_tag_get(data, "rainTime"),
        raining=_tag_get(data, "raining"),
        thunder_time=_tag_get(data, "thunderTime"),
        thundering=_tag_get(data, "thundering"),
        version_series=_tag_get(version_tag, "Series"),
        version_snapshot=_tag_get(version_tag, "Snapshot"),
        data_packs=data_packs,
        server_brands=server_brands,
        was_modded=_tag_get(data, "WasModded"),
        clear_weather_time=_tag_get(data, "clearWeatherTime"),
        initialized=_tag_get(data, "initialized"),
        difficulty_locked=_tag_get(data, "DifficultyLocked"),
        spawn_angle=_tag_get(data, "SpawnAngle"),
        generate_features=generate_features,
        bonus_chest=bonus_chest,
        border_center_x=_tag_get(data, "BorderCenterX"),
        border_center_z=_tag_get(data, "BorderCenterZ"),
        border_size=_tag_get(data, "BorderSize"),
        border_warning_blocks=_tag_get(data, "BorderWarningBlocks"),
        mods=list(mod_metadata.mods),
        mod_loaders=list(mod_metadata.loaders),
        mod_list_complete=mod_metadata.list_complete,
    )


class NbtLoader:
    """NBT 数据延迟加载器。"""

    def __init__(
        self,
        world_path: Path,
        log_callback: Optional[LogFn] = None,
    ) -> None:
        """初始化加载器。

        Args:
            world_path: 世界根目录。
            log_callback: 可选日志回调 ``(message, level)``。
        """
        self.world_path = world_path
        self._log: LogFn = log_callback or (lambda msg, lvl="INFO": None)
        self._level_data: Optional[File] = None
        self._world_info: Optional[WorldInfo] = None
        self._loaded_player_data: Dict[str, Compound] = {}
        self._loaded_regions: Dict[Tuple[int, int], Path] = {}

    def load_level_info(self) -> WorldInfo:
        """读取 level.dat 并提取完整信息。

        Returns:
            WorldInfo: 缓存的世界信息快照。

        Raises:
            FileNotFoundError: ``level.dat`` 不存在。
            RuntimeError: NBT 解析失败。
        """
        if self._world_info is not None:
            return self._world_info

        level_path = self.world_path / "level.dat"
        if not level_path.exists():
            self._log(
                "未找到 level.dat，这可能不是有效的 Minecraft 存档目录",
                "WARNING",
            )
            raise FileNotFoundError(f"未找到 level.dat: {level_path}")

        try:
            self._level_data = nbtlib.load(level_path)
            self._world_info = build_world_info_from_level_root(self._level_data)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self._log(
                f"解析 level.dat 失败: {type(exc).__name__}: {exc}",
                "ERROR",
            )
            raise RuntimeError(
                f"NBT 解析失败 ({level_path.name}): "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        except Exception as exc:
            self._log(
                f"解析 level.dat 失败: {type(exc).__name__}: {exc}",
                "ERROR",
            )
            raise RuntimeError(
                f"NBT 解析失败 ({level_path.name}): "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        self._log(
            f"已加载存档信息：版本 {self._world_info.version} "
            f"({self._world_info.version_name})",
            "INFO",
        )
        return self._world_info

    def get_level_data(self) -> Optional[File]:
        """获取已加载的 level.dat 数据。"""
        return self._level_data

    def load_player_data(
        self,
        uuid: str,
        player_files: Dict[str, Path],
    ) -> Optional[Compound]:
        """延迟加载指定 UUID 的玩家数据文件。

        Args:
            uuid: 玩家 UUID（规范化后）。
            player_files: UUID → 文件路径映射。

        Returns:
            Compound | None: 玩家 NBT；加载失败为 None。
        """
        if uuid in self._loaded_player_data:
            return self._loaded_player_data[uuid]
        if uuid not in player_files:
            self._log(f"玩家 UUID 不存在: {uuid}", "WARNING")
            return None

        path = player_files[uuid]
        try:
            data = nbtlib.load(path)
            self._loaded_player_data[uuid] = data
            return data
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self._log(f"加载玩家数据 {uuid} 失败: {exc}", "ERROR")
            return None
        except Exception as exc:
            self._log(f"加载玩家数据 {uuid} 失败: {exc}", "ERROR")
            return None

    def load_chunk_nbt(
        self,
        region_path: Path,
        chunk_x: int,
        chunk_z: int,
    ) -> Optional[Tuple[Any, Path]]:
        """加载指定区块的 NBT 数据。

        Args:
            region_path: 相对存档根目录的区域文件路径。
            chunk_x: 区域内区块 X（0–31）。
            chunk_z: 区域内区块 Z（0–31）。

        Returns:
            tuple | None: ``(区块数据, 绝对路径)``；失败为 None。
        """
        try:
            abs_region_path = self.world_path / region_path
            if not abs_region_path.exists():
                self._log(f"区域文件不存在: {region_path}", "ERROR")
                return None

            from core.mca import NativeRegion

            with NativeRegion.from_file(abs_region_path) as region:
                chunk = region.get_chunk(chunk_x, chunk_z)
                if chunk is None or chunk.data is None:
                    self._log(
                        f"区块数据不存在: {region_path} [{chunk_x}, {chunk_z}]",
                        "WARNING",
                    )
                    return None
                self._log(
                    f"已加载区块: {region_path} [{chunk_x}, {chunk_z}]",
                    "INFO",
                )
                return chunk.data, abs_region_path
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            self._log(f"加载区块失败: {exc}", "ERROR")
            return None
        except Exception as exc:
            self._log(f"加载区块失败: {exc}", "ERROR")
            return None

    def cache_region(self, x: int, z: int, path: Path) -> None:
        """缓存区域文件路径。

        Args:
            x: 区域 X。
            z: 区域 Z。
            path: 区域文件路径。
        """
        self._loaded_regions[(x, z)] = path
