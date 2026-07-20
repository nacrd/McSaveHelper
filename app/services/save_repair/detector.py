"""World Detector - 只读检测服务

检测存档状态，不修改任何文件。
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Set

import nbtlib

from core.constants import MinecraftConstants
from core.scanner import scan_all_regions
from core.utils import list_player_dat_files

from .level_repairer import LEVEL_DAT_REQUIRED_FIELDS
from .models import DetectReport, WorldInfo
from .player_repairer import PLAYER_REQUIRED_FIELDS
from .validation_utils import (
    count_damaged_chunks,
    validate_level_dat_data,
    validate_player_data,
)

LogFn = Callable[[str, str], None]
ProgressFn = Callable[[float, str], None]

# 游戏模式和难度名称映射
_GAME_TYPE_NAMES = {0: "生存", 1: "创造", 2: "冒险", 3: "旁观"}
_DIFFICULTY_NAMES = {0: "和平", 1: "简单", 2: "普通", 3: "困难"}
_S_IFREG = 0o100000
_S_IFMT = 0o170000


@dataclass(frozen=True)
class RegionDetectionResult:
    """单个区域文件的只读检测结果。"""

    damaged_chunks: int = 0
    unreadable_error: Optional[str] = None


def _read_int_tag(
    compound: nbtlib.tag.Compound,
    key: str,
    default: int,
) -> int:
    """读取可能缺失或损坏的整数标签。

    Args:
        compound: NBT Compound。
        key: 字段名。
        default: 缺失或无法转换时的默认值。

    Returns:
        int: 解析后的整数值或默认值。
    """
    value = compound.get(key)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def dimension_for_region_parts(parts: tuple[str, ...]) -> Optional[str]:
    """从区域文件相对路径识别 Minecraft 维度 ID。

    Args:
        parts: 相对世界根的路径部件。

    Returns:
        str | None: 如 ``minecraft:overworld``；无法识别时为 None。
    """
    if len(parts) >= 2 and parts[0] == "region":
        return "minecraft:overworld"
    if len(parts) >= 3 and parts[0] == "DIM-1":
        return "minecraft:the_nether"
    if len(parts) >= 3 and parts[0] == "DIM1":
        return "minecraft:the_end"
    if len(parts) >= 5 and parts[:2] == ("dimensions", "minecraft"):
        return f"minecraft:{parts[2]}"
    if "dimensions" not in parts:
        return None
    index = parts.index("dimensions")
    if index + 2 >= len(parts):
        return None
    return f"{parts[index + 1]}:{parts[index + 2]}"


def estimate_region_chunks(region_files: List[Path]) -> int:
    """按文件大小粗略估计区域中的区块数（上限 1024/文件）。

    Args:
        region_files: 区域文件路径列表。

    Returns:
        int: 估计区块总数。
    """
    total_chunks = 0
    for region_file in region_files:
        try:
            size = region_file.stat().st_size
        except OSError:
            continue
        total_chunks += min(1024, max(0, size // 4096))
    return total_chunks


class WorldDetector:
    """存档检测器（只读）。

    汇总世界元数据、区域损坏统计、玩家数据问题与 level.dat 校验结果，
    不写入或移动任何世界文件。
    """

    def __init__(self, cancel_event: threading.Event) -> None:
        """初始化检测器。

        Args:
            cancel_event: 协作式取消事件。
        """
        self._cancel_event = cancel_event

    @property
    def is_cancelled(self) -> bool:
        """当前检测是否已被请求取消。"""
        return self._cancel_event.is_set()

    def detect_world(
        self,
        world_path: Path,
        report: DetectReport,
        log: LogFn,
        progress: ProgressFn,
    ) -> None:
        """检测存档状态（只读，不修改任何文件）。

        Args:
            world_path: 世界根目录。
            report: 可变检测报告。
            log: 日志回调。
            progress: 进度回调 ``(fraction, label)``。
        """
        progress(0.05, "读取世界信息...")
        region_files = self._detect_world_info(world_path, report, log)

        progress(0.15, "扫描区块文件...")
        self._detect_chunks(world_path, report, log, progress, region_files)

        progress(0.80, "检测玩家数据...")
        self._detect_players(world_path, report, log)

        progress(0.92, "检测 level.dat...")
        self._detect_level_dat(world_path, report, log)

    def _detect_world_info(
        self,
        world_path: Path,
        report: DetectReport,
        log: LogFn,
    ) -> List[Path]:
        """读取世界基本信息并返回区域文件列表。"""
        info = report.world_info
        info.world_name = world_path.name
        info.world_size_mb, info.total_files = self._measure_world_size(world_path)
        info.has_level_dat = (world_path / "level.dat").exists()

        if info.has_level_dat:
            self._read_level_dat_info(world_path, info, log)

        region_files = self._detect_dimensions(world_path, info)
        info.player_count = len(list_player_dat_files(world_path))

        log(
            f"世界: {info.world_name}, 版本: {info.version_name}, "
            f"大小: {info.world_size_mb:.1f}MB, 区域: {info.region_count}, "
            f"玩家: {info.player_count}",
            "INFO",
        )
        return region_files

    @staticmethod
    def _measure_world_size(world_path: Path) -> tuple[float, int]:
        """统计世界目录下普通文件总大小与数量。"""
        total_size = 0
        file_count = 0
        for entry in world_path.rglob("*"):
            try:
                st = entry.stat()
            except OSError:
                continue
            if st.st_mode & _S_IFMT == _S_IFREG:
                total_size += st.st_size
                file_count += 1
        return total_size / (1024 * 1024), file_count

    def _read_level_dat_info(
        self,
        world_path: Path,
        info: WorldInfo,
        log: LogFn,
    ) -> None:
        """从 level.dat 填充版本、模式、难度与出生点等字段。"""
        try:
            nbt_data = nbtlib.load(str(world_path / "level.dat"))
            data = nbt_data.get("Data")
            if not isinstance(data, nbtlib.tag.Compound):
                return
            info.data_version = _read_int_tag(data, "DataVersion", 0)
            info.version_name = MinecraftConstants.VERSION_MAP.get(
                info.data_version,
                f"未知({info.data_version})",
            )
            info.game_type = _read_int_tag(data, "GameType", 0)
            info.game_type_name = _GAME_TYPE_NAMES.get(info.game_type, "未知")
            info.difficulty = _read_int_tag(data, "Difficulty", 2)
            info.difficulty_name = _DIFFICULTY_NAMES.get(info.difficulty, "未知")
            info.seed = _read_int_tag(data, "RandomSeed", 0)
            info.spawn_pos = (
                _read_int_tag(data, "SpawnX", 0),
                _read_int_tag(data, "SpawnY", 64),
                _read_int_tag(data, "SpawnZ", 0),
            )
            info.play_time_ticks = _read_int_tag(data, "Time", 0)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            log(f"无法读取 level.dat 基本信息: {exc}", "WARNING")
        except Exception as exc:
            log(f"无法读取 level.dat 基本信息: {exc}", "WARNING")

    def _detect_dimensions(
        self,
        world_path: Path,
        info: WorldInfo,
        region_files: Optional[List[Path]] = None,
    ) -> List[Path]:
        """检测维度和区域文件（兼容 Minecraft 26.1 新旧路径）。"""
        if region_files is None:
            region_files = scan_all_regions(world_path)
        info.region_count = len(region_files)
        dimensions: Set[str] = set()

        for region_file in region_files:
            parts = region_file.relative_to(world_path).parts
            dimension = dimension_for_region_parts(parts)
            if dimension is not None:
                dimensions.add(dimension)

        info.dimensions = sorted(dimensions)
        info.total_chunks = estimate_region_chunks(region_files)
        return region_files

    def _detect_chunks(
        self,
        world_path: Path,
        report: DetectReport,
        log: LogFn,
        progress: ProgressFn,
        region_files: Optional[List[Path]] = None,
    ) -> None:
        """并行检测区域文件中的损坏区块。"""
        if region_files is None:
            region_files = scan_all_regions(world_path)
        total = len(region_files)
        if total == 0:
            log("未找到区块文件", "WARNING")
            return

        log(f"找到 {total} 个区域文件，开始逐块检测...", "INFO")
        report.chunks_checked = total * 1024
        max_workers = min(max(1, (total + 3) // 4), 8)

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(self._detect_region, region_file, log): region_file
                for region_file in region_files
            }
            completed = 0
            for future in as_completed(futures):
                if self.is_cancelled:
                    pool.shutdown(wait=False, cancel_futures=True)
                    break
                region_file = futures[future]
                try:
                    result = future.result(timeout=120)
                except TimeoutError as exc:
                    log(f"检测 {region_file.name} 超时: {exc}", "ERROR")
                except (OSError, ValueError, RuntimeError) as exc:
                    log(f"检测 {region_file.name} 异常: {exc}", "ERROR")
                except Exception as exc:
                    log(f"检测 {region_file.name} 异常: {exc}", "ERROR")
                else:
                    report.chunks_damaged += result.damaged_chunks
                    if result.unreadable_error is not None:
                        report.unreadable_regions.append(region_file.name)
                completed += 1
                progress(
                    0.15 + (completed / total) * 0.65,
                    f"检测区块文件 {completed}/{total}",
                )

    def _detect_region(
        self,
        region_file: Path,
        log: LogFn,
    ) -> RegionDetectionResult:
        """检测单个区域文件。"""
        if self.is_cancelled:
            return RegionDetectionResult()
        try:
            damaged = self._count_damaged_chunks(region_file)
        except (OSError, ValueError, RuntimeError) as exc:
            message = f"无法读取: {exc}"
            log(f"无法读取区域文件 {region_file.name}: {exc}", "ERROR")
            return RegionDetectionResult(unreadable_error=message)
        except Exception as exc:
            message = f"无法读取: {exc}"
            log(f"无法读取区域文件 {region_file.name}: {exc}", "ERROR")
            return RegionDetectionResult(unreadable_error=message)

        if damaged:
            log(f"{region_file.name}: {damaged} 个损坏区块", "WARNING")
        return RegionDetectionResult(damaged)

    def _count_damaged_chunks(self, region_file: Path) -> int:
        """统计区域中损坏区块数（忽略 completed 标志）。"""
        damaged, _completed = count_damaged_chunks(
            region_file,
            lambda: self.is_cancelled,
        )
        return damaged

    def _detect_players(
        self,
        world_path: Path,
        report: DetectReport,
        log: LogFn,
    ) -> None:
        """检测玩家数据（兼容 Minecraft 26.1 新旧路径）。"""
        player_files = list_player_dat_files(world_path)
        if not player_files:
            log("玩家数据目录不存在", "INFO")
            return

        report.players_checked = len(player_files)
        log(f"找到 {len(player_files)} 个玩家数据文件", "INFO")

        for player_file in player_files:
            if self.is_cancelled:
                break
            issues = self._player_issues(player_file)
            if not issues:
                continue
            report.players_with_issues += 1
            report.player_issues[player_file.name] = issues
            log(f"玩家 {player_file.name}: {'; '.join(issues)}", "WARNING")

    @staticmethod
    def _player_issues(player_file: Path) -> List[str]:
        """返回单个玩家文件的问题描述列表。"""
        try:
            nbt_data = nbtlib.load(str(player_file))
            return validate_player_data(nbt_data, list(PLAYER_REQUIRED_FIELDS))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            return [f"无法读取: {exc}"]
        except Exception as exc:
            return [f"无法读取: {exc}"]

    def _detect_level_dat(
        self,
        world_path: Path,
        report: DetectReport,
        log: LogFn,
    ) -> None:
        """检测 level.dat 是否存在且结构可接受。"""
        level_dat = world_path / "level.dat"
        level_dat_old = world_path / "level.dat_old"

        if not level_dat.exists():
            report.level_dat_ok = False
            report.level_dat_issues.append("level.dat 不存在")
            if level_dat_old.exists():
                report.level_dat_issues.append("可用 level.dat_old 恢复")
                log("level.dat 不存在，但 level.dat_old 可用", "WARNING")
            else:
                report.level_dat_issues.append(
                    "level.dat_old 也不存在，无法恢复"
                )
                log("level.dat 和 level.dat_old 都不存在", "ERROR")
            return

        try:
            nbt_data = nbtlib.load(str(level_dat))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            report.level_dat_ok = False
            report.level_dat_issues.append(f"NBT 解析失败: {exc}")
            log(f"level.dat 无法解析: {exc}", "ERROR")
            return
        except Exception as exc:
            report.level_dat_ok = False
            report.level_dat_issues.append(f"NBT 解析失败: {exc}")
            log(f"level.dat 无法解析: {exc}", "ERROR")
            return

        if "Data" not in nbt_data:
            report.level_dat_ok = False
            report.level_dat_issues.append("缺少 Data 字段")
            log("level.dat 缺少 Data 字段", "ERROR")
            return

        data = nbt_data["Data"]
        if not isinstance(data, nbtlib.tag.Compound):
            report.level_dat_ok = False
            report.level_dat_issues.append("Data 字段类型错误")
            log("level.dat 的 Data 字段类型错误", "ERROR")
            return

        issues = validate_level_dat_data(data, LEVEL_DAT_REQUIRED_FIELDS)
        report.level_dat_issues = issues
        report.level_dat_ok = len(issues) == 0

        if report.level_dat_ok:
            log("level.dat 验证通过", "INFO")
            return
        for issue in report.level_dat_issues:
            log(f"level.dat: {issue}", "WARNING")
