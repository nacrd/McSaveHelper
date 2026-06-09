"""
NbtLoader - NBT 数据延迟加载器
负责按需加载和缓存 NBT 文件（玩家数据、level.dat 等）
"""
from pathlib import Path
from typing import Dict, Optional, Callable, Any, Tuple
import nbtlib
from nbtlib import Compound, File
from .models import WorldInfo


class NbtLoader:
    """NBT 数据延迟加载器"""

    def __init__(self, world_path: Path, log_callback: Optional[Callable] = None):
        self.world_path = world_path
        self._log = log_callback or (lambda msg, lvl="INFO": None)

        # 缓存
        self._level_data: Optional[File] = None
        self._world_info: Optional[WorldInfo] = None
        self._loaded_player_data: Dict[str, Compound] = {}
        self._loaded_regions: Dict[Tuple[int, int], Path] = {}

    def load_level_info(self) -> WorldInfo:
        """读取 level.dat 并提取完整信息

        Returns:
            WorldInfo 对象

        Raises:
            FileNotFoundError: level.dat 不存在
            RuntimeError: NBT 解析失败
        """
        if self._world_info is not None:
            return self._world_info

        level_path = self.world_path / "level.dat"
        if not level_path.exists():
            self._log("未找到 level.dat，这可能不是有效的 Minecraft 存档目录", "WARNING")
            raise FileNotFoundError(f"未找到 level.dat: {level_path}")

        try:
            self._level_data = nbtlib.load(level_path)
            root = self._level_data
            data = root.get("Data") or {}

            # 提取版本信息
            version_tag = data.get("Version", {})
            version = version_tag.get("Id", 0) if version_tag else 0
            version_name = version_tag.get("Name", None) if version_tag else None
            version_series = version_tag.get("Series", None) if version_tag else None
            version_snapshot = version_tag.get("Snapshot", None) if version_tag else None

            # 提取世界基本信息
            game_type = data.get("GameType", None)
            last_played = data.get("LastPlayed", None)
            spawn_x = data.get("SpawnX", None)
            spawn_y = data.get("SpawnY", None)
            spawn_z = data.get("SpawnZ", None)
            level_name = data.get("LevelName", None)
            difficulty = data.get("Difficulty", None)
            hardcore = data.get("hardcore", None)
            allow_commands = data.get("allowCommands", None)

            # 提取时间和天气信息
            day_time = data.get("DayTime", None)
            time = data.get("Time", None)
            rain_time = data.get("rainTime", None)
            raining = data.get("raining", None)
            thunder_time = data.get("thunderTime", None)
            thundering = data.get("thundering", None)
            clear_weather_time = data.get("clearWeatherTime", None)

            # 提取种子
            seed = None
            wgs = data.get("WorldGenSettings")
            if wgs:
                seed = wgs.get("seed", None)

            # 提取数据包信息
            data_packs = None
            dp = data.get("DataPacks")
            if dp:
                enabled = dp.get("Enabled", [])
                disabled = dp.get("Disabled", [])
                if enabled or disabled:
                    data_packs = {
                        "enabled": [str(e) for e in enabled] if enabled else [],
                        "disabled": [str(d) for d in disabled] if disabled else [],
                    }

            # 提取其他信息
            server_brands = data.get("ServerBrands", None)
            was_modded = data.get("WasModded", None)
            initialized = data.get("initialized", None)

            self._world_info = WorldInfo(
                version=version,
                version_name=version_name,
                game_type=game_type,
                last_played=last_played,
                spawn_x=spawn_x,
                spawn_y=spawn_y,
                spawn_z=spawn_z,
                level_name=level_name,
                difficulty=difficulty,
                hardcore=hardcore,
                allow_commands=allow_commands,
                seed=seed,
                day_time=day_time,
                time=time,
                rain_time=rain_time,
                raining=raining,
                thunder_time=thunder_time,
                thundering=thundering,
                version_series=version_series,
                version_snapshot=version_snapshot,
                data_packs=data_packs,
                server_brands=server_brands,
                was_modded=was_modded,
                clear_weather_time=clear_weather_time,
                initialized=initialized,
            )

            self._log(f"已加载存档信息：版本 {version} ({version_name})", "INFO")
            return self._world_info

        except Exception as e:
            self._log(f"解析 level.dat 失败: {type(e).__name__}: {e}", "ERROR")
            raise RuntimeError(f"NBT 解析失败 ({level_path.name}): {type(e).__name__}: {e}") from e

    def get_level_data(self) -> Optional[File]:
        """获取已加载的 level.dat 数据"""
        return self._level_data

    def load_player_data(self, uuid: str, player_files: Dict[str, Path]) -> Optional[Compound]:
        """延迟加载指定 UUID 的玩家数据文件

        Args:
            uuid: 玩家 UUID（规范化后）
            player_files: UUID -> 文件路径的映射

        Returns:
            玩家数据的 NBT 标签，若加载失败则返回 None
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
        except Exception as e:
            self._log(f"加载玩家数据 {uuid} 失败: {e}", "ERROR")
            return None

    def load_chunk_nbt(self, region_path: Path, chunk_x: int, chunk_z: int) -> Optional[Tuple[Any, Path]]:
        """加载指定区块的 NBT 数据

        Args:
            region_path: 相对存档根目录的区域文件路径
            chunk_x: 区块在区域内的 X 坐标 (0-31)
            chunk_z: 区块在区域内的 Z 坐标 (0-31)

        Returns:
            (区块数据, 绝对路径) 或 None
        """
        try:
            abs_region_path = self.world_path / region_path
            if not abs_region_path.exists():
                self._log(f"区域文件不存在: {region_path}", "ERROR")
                return None

            from anvil import Region
            region = Region.from_file(str(abs_region_path))
            chunk = region.get_chunk(chunk_x, chunk_z)

            if chunk is None or not hasattr(chunk, "data"):
                self._log(f"区块数据不存在: {region_path} [{chunk_x}, {chunk_z}]", "WARNING")
                return None

            self._log(f"已加载区块: {region_path} [{chunk_x}, {chunk_z}]", "INFO")
            return chunk.data, abs_region_path

        except Exception as e:
            self._log(f"加载区块失败: {e}", "ERROR")
            return None

    def cache_region(self, x: int, z: int, path: Path) -> None:
        """缓存区域文件路径"""
        self._loaded_regions[(x, z)] = path
