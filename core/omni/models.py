"""
数据模型定义 - WorldSession 相关的数据类
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable


@dataclass(frozen=True)
class ModInfo:
    """One mod entry recorded or inferred from world metadata."""

    mod_id: str
    version: Optional[str] = None
    name: Optional[str] = None


@dataclass
class WorldInfo:
    """从 level.dat 提取的完整信息"""
    version: int
    version_name: Optional[str] = None
    game_type: Optional[int] = None
    last_played: Optional[int] = None
    spawn_x: Optional[int] = None
    spawn_y: Optional[int] = None
    spawn_z: Optional[int] = None
    level_name: Optional[str] = None
    difficulty: Optional[int] = None
    hardcore: Optional[bool] = None
    allow_commands: Optional[bool] = None
    seed: Optional[int] = None
    day_time: Optional[int] = None
    time: Optional[int] = None
    rain_time: Optional[int] = None
    raining: Optional[bool] = None
    thunder_time: Optional[int] = None
    thundering: Optional[bool] = None
    version_series: Optional[str] = None
    version_snapshot: Optional[bool] = None
    data_packs: Optional[Dict[str, List[str]]] = None
    server_brands: Optional[List[str]] = None
    was_modded: Optional[bool] = None
    clear_weather_time: Optional[int] = None
    initialized: Optional[bool] = None
    difficulty_locked: Optional[bool] = None
    spawn_angle: Optional[float] = None
    generate_features: Optional[bool] = None
    bonus_chest: Optional[bool] = None
    border_center_x: Optional[float] = None
    border_center_z: Optional[float] = None
    border_size: Optional[float] = None
    border_warning_blocks: Optional[int] = None
    mods: Optional[List[ModInfo]] = None
    mod_loaders: Optional[List[str]] = None
    mod_list_complete: bool = False


@dataclass
class Action:
    """代表一个待执行的操作"""
    type: str  # NBT/JSON edit, region delete, player rename, custom, or chunk edit.
    target: Any  # 文件路径、坐标、UUID 等
    data: Any = None
    callback: Optional[Callable] = None


@dataclass
class ChunkTarget:
    """区块编辑目标"""
    region_path: Path  # 相对存档根目录的路径
    chunk_x: int
    chunk_z: int
    full_chunk_data: Any  # 完整的区块 NBT 数据
